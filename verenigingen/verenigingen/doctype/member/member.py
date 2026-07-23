"""
Member DocType - Core business entity for association membership management.

This module implements the Member DocType, which serves as the central entity
for managing association members throughout their lifecycle.

Key Features:
    - Member identification and lifecycle management
    - Chapter membership integration
    - Payment processing and SEPA mandate handling
    - Expense claim management
    - Termination workflow processing
    - Dutch address normalization and matching
    - Audit trail and history tracking

Architecture:
    - Uses mixin pattern for feature separation
    - Optimized address matching with fingerprinting
    - Dutch naming convention support
    - Performance-optimized field updates

Mixins:
    - PaymentMixin: Payment processing and billing
    - ExpenseMixin: Expense claim handling
    - SEPAMandateMixin: SEPA direct debit management
    - ChapterMixin: Chapter membership operations
    - TerminationMixin: Membership termination workflow
    - FinancialMixin: Financial data management

Author: Verenigingen Development Team
Last Updated: 2025-08-02
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.services.member.core.member_address_service import get_member_address_service
from verenigingen.services.member.core.member_id_service import generate_application_id, generate_member_id
from verenigingen.services.member.core.member_status_service import (
    is_application_member,
    set_member_application_status_defaults,
    sync_member_status_fields,
    update_member_membership_status,
)
from verenigingen.services.member.utils.member_age_service import (
    update_member_age_field,
    validate_member_age_requirements,
)

# Extracted services
from verenigingen.services.member.utils.membership_duration_service import (
    calculate_total_membership_days as calculate_duration_days,
)
from verenigingen.utils.constants import Roles
from verenigingen.utils.dutch_name_service import update_member_full_name, validate_member_name_fields
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
    high_security_api,
    standard_api,
)

# Migrated from old security_decorators to new api_security_framework
from verenigingen.verenigingen.doctype.member.mixins.chapter_mixin import ChapterMixin
from verenigingen.verenigingen.doctype.member.mixins.expense_mixin import ExpenseMixin
from verenigingen.verenigingen.doctype.member.mixins.financial_mixin import FinancialMixin
from verenigingen.verenigingen.doctype.member.mixins.payment_mixin import PaymentMixin
from verenigingen.verenigingen.doctype.member.mixins.sepa_mixin import SEPAMandateMixin
from verenigingen.verenigingen.doctype.member.mixins.termination_mixin import TerminationMixin


class Member(
    Document, PaymentMixin, ExpenseMixin, SEPAMandateMixin, ChapterMixin, TerminationMixin, FinancialMixin
):
    """
    Core Member DocType with refactored structure using mixins for better organization.

    This class represents a member of the association and manages all aspects
    of membership including personal information, chapter affiliations, payments,
    expenses, and termination processes.

    Key Responsibilities:
        - Member identification and ID generation
        - Address normalization and matching
        - Chapter display updates
        - Application status management
        - Performance-optimized field updates

    Inherited Capabilities (via Mixins):
        - Payment processing and billing (PaymentMixin)
        - Expense claim management (ExpenseMixin)
        - SEPA mandate handling (SEPAMandateMixin)
        - Chapter operations (ChapterMixin)
        - Termination workflows (TerminationMixin)
        - Financial data management (FinancialMixin)

    Performance Optimizations:
        - Conditional field updates based on change detection
        - Cached address fingerprinting for matching
        - Efficient chapter display computation
        - Minimal database queries during save operations

    Business Rules:
        - Member IDs generated only for approved members
        - Application IDs for pending applications
        - Address fingerprinting for duplicate detection
        - Dutch naming convention support
    """

    def before_save(self) -> None:
        """Execute before saving the document with optimized performance.

        EXTRACTED: Moved to MemberBeforeSaveService.execute_before_save()
        for service layer separation.

        Operations:
            1. Safe performance optimization (metadata caching, link batching)
            2. Member/Application ID generation (conditional)
            3. Chapter display updates (when needed)
            4. Address normalization (when address changes)
            5. Application status defaults
            6. Counter reset handling
        """
        from verenigingen.services.member.lifecycle.member_before_save_service import (
            get_member_before_save_service,
        )

        get_member_before_save_service().execute_before_save(self)

    def _should_update_chapter_display(self):
        """
        Check if chapter display needs updating to avoid unnecessary processing.

        EXTRACTED: Moved to MemberChapterDisplayService.should_update_chapter_display()
        for service layer separation (Phase 2D-3).
        """
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )

        return get_member_chapter_display_service().should_update_chapter_display(self)

    def _update_computed_address_fields(self):
        """Update computed address fields - delegates to MemberAddressService."""
        get_member_address_service().execute_address_field_update(self)

    def _validate_fee_override_amount(self, amount):
        """
        Validate fee override amount is positive.

        EXTRACTED: Moved to MemberFeeValidationService.validate_fee_override_amount()
        for service layer separation (Phase 2D-2).
        """
        from verenigingen.services.member.financial.member_fee_validation_service import (
            get_member_fee_validation_service,
        )

        get_member_fee_validation_service().validate_fee_override_amount(amount)

    def _validate_fee_override_reason(self):
        """
        Validate fee override has documented reason when required.

        EXTRACTED: Moved to MemberFeeValidationService.validate_fee_override_reason()
        for service layer separation (Phase 2D-2).
        """
        from verenigingen.services.member.financial.member_fee_validation_service import (
            get_member_fee_validation_service,
        )

        get_member_fee_validation_service().validate_fee_override_reason(self)

    def validate_fee_override_permissions(self):
        """
        Validate that only authorized users can set fee overrides.

        EXTRACTED: Moved to MemberFeeValidationService.validate_fee_override_permissions()
        for service layer separation (Phase 2D-2).
        """
        from verenigingen.services.member.financial.member_fee_validation_service import (
            get_member_fee_validation_service,
        )

        get_member_fee_validation_service().validate_fee_override_permissions(self)

    def has_permission(self, ptype="read", user=None):
        """
        Override permission check to bypass User Permission restrictions for VBCM users.

        This method is called by Frappe's permission system BEFORE User Permission checks.
        It allows Chapter Board Members to access Member records in their chapters even if
        those members are linked to Employee records the board member doesn't have User Permission for.

        Args:
            ptype: Permission type (read, write, etc.)
            user: User to check permissions for

        Returns:
            True if permission granted, False otherwise
        """
        if not user:
            user = frappe.session.user

        # Import here to avoid circular import
        from verenigingen.permissions import has_member_permission

        # Use our custom permission function which handles chapter-based access
        # This will return True for VBCM users who have access to this member's chapter
        # regardless of Employee User Permission restrictions
        return has_member_permission(self, user, ptype)

    @staticmethod
    def has_query_permission(user):
        """
        Override query permission to bypass User Permission filtering on list views.

        This method is called by Frappe when building list view queries with write permissions.
        It prevents User Permission restrictions (like Employee permissions) from filtering
        the Member list for VBCM users who should see all members in their chapters.

        Args:
            user: User to check permissions for

        Returns:
            True to skip User Permission filtering, None to use default behavior
        """
        if not user:
            user = frappe.session.user

        user_roles = frappe.get_roles(user)

        # Admin roles always have full access
        admin_roles = Roles.ADMIN_ROLES
        if any(role in user_roles for role in admin_roles):
            return True

        # For VBCM users, bypass User Permission filtering
        # The actual filtering is handled by get_member_permission_query
        if "Verenigingen Chapter Board Member" in user_roles:
            return True

        # For other users, use default Frappe permission behavior
        return None

    def before_insert(self):
        """Execute before inserting new document"""
        # Member ID generation is now handled in before_save based on application status

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def get_address_members_html(self) -> str:
        """Get HTML content for address members field - delegates to MemberAddressDisplayService"""
        from verenigingen.services.member.display.member_address_display_service import (
            get_member_address_display_service,
        )

        return get_member_address_display_service().get_address_members_html(self)

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def get_volunteer_details_html(self) -> str:
        """Get HTML content for volunteer details field."""
        from verenigingen.services.member.display.member_volunteer_display_service import (
            get_member_volunteer_display_service,
        )

        return get_member_volunteer_display_service().generate_volunteer_details_html(self) or ""

    def _get_status_color(self, status):
        """Get Bootstrap color class for member status - delegated to member_status_service"""
        from verenigingen.services.member.core.member_status_service import get_member_status_color

        return get_member_status_color(status)

    @frappe.whitelist()
    @development_only_api(operation_type=OperationType.UTILITY)
    def after_save(self) -> None:
        """Execute after saving the document"""
        # Note: IBAN history creation is handled in two ways:
        # 1. For application members: During application approval in membership_application_review.py
        # 2. For directly created members: Should be created manually after member creation

        # Create user account for manually created members (non-application members)
        # Application members get user accounts created during the approval process
        if not self.is_application_member() and not self.user and self.email:
            # Only create user account if member doesn't have one and has an email
            self.create_user_account_if_needed()

    def create_user_account_if_needed(self):
        """
        Create user account for member if conditions are met.

        EXTRACTED: Moved to MemberUserAccountService.create_user_account_if_needed()
        for service layer separation.
        """
        from verenigingen.services.member.account.member_user_account_service import (
            get_member_user_account_service,
        )

        get_member_user_account_service().create_user_account_if_needed(self)

    def onload(self):
        """Execute when document is loaded.

        EXTRACTED: Moved to MemberOnloadService.execute_onload()
        for service layer separation.
        """
        try:
            from verenigingen.services.member.display.member_onload_service import (
                get_member_onload_service,
            )

            get_member_onload_service().execute_onload(self)
        except Exception as e:
            frappe.log_error(f"Critical error in onload method for {self.name}: {e}")
            # Don't raise exception to prevent form loading issues

    def is_application_member(self) -> bool:
        """Check if this member was created through the application process.

        Delegates to member_status_service.is_application_member - the
        single source of truth after T4.1's MemberLifecycleService retirement.
        """
        return is_application_member(self)

    def should_have_member_id(self) -> bool:
        """Check if this member should have a member ID assigned"""
        # Non-application members should get member ID immediately
        if not self.is_application_member():
            return True

        # Application members only get member ID when approved
        return getattr(self, "application_status", "") == "Approved"

    def generate_member_id(self):
        """Generate a unique member ID - delegated to member_id_service"""
        return generate_member_id()

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.ADMIN)
    def ensure_member_id(self) -> Optional[str]:
        """Ensure this member has a member ID if they should have one - delegated to member_id_service"""
        from verenigingen.services.member.core.member_id_service import ensure_member_has_id

        return ensure_member_has_id(self)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def force_assign_member_id(self) -> str:
        """Force assign a member ID regardless of normal rules (admin only) - delegated to member_id_service"""
        from verenigingen.services.member.core.member_id_service import force_assign_member_id

        return force_assign_member_id(self)

    # Member.approve_application removed in T4.1. It was a deprecated
    # whitelisted wrapper around MemberLifecycleService.approve_application
    # with no production callers. The canonical approval path lives at
    # api.membership_application_review.approve_membership_application; it
    # calls member.create_membership_on_approval() directly.

    def create_membership_on_approval(
        self,
        start_date=None,
        create_invoice=True,
        custom_dues_rate=None,
        custom_rate_reason=None,
        is_csv_import=False,
        approval_fields=None,
    ):
        """
        Create membership record when application is approved.

        EXTRACTED: Moved to MembershipCreationService.create_membership_on_approval()
        for service layer separation.
        """
        from verenigingen.services.member.approval.membership_creation_service import (
            MembershipCreationService,
        )

        return MembershipCreationService().create_membership_on_approval(
            self,
            start_date=start_date,
            create_invoice=create_invoice,
            custom_dues_rate=custom_dues_rate,
            custom_rate_reason=custom_rate_reason,
            is_csv_import=is_csv_import,
            approval_fields=approval_fields,
        )

    # Member.reject_application removed in T4.1, same reasoning as
    # approve_application. The canonical rejection path is
    # api.membership_application_review.reject_membership_application.

    def validate(self) -> None:
        """Validate document data with optional performance optimizations.

        EXTRACTED: Moved to MemberValidationService.execute_validation()
        for service layer separation.
        """
        from verenigingen.services.member.validation.member_validation_service import (
            get_member_validation_service,
        )

        get_member_validation_service().execute_validation(self)

    def on_update(self):
        """Emit events for status changes to trigger background operations.

        EXTRACTED: Moved to MemberEventEmissionService.emit_status_change_events()
        for service layer separation.
        """
        from verenigingen.services.member.lifecycle.member_event_emission_service import (
            get_member_event_emission_service,
        )

        get_member_event_emission_service().emit_status_change_events(self)

    def on_change(self):
        """Runs after all on_update hooks complete (including doc_event hooks).

        Workaround for Frappe bug: process_workflow_actions (a global on_update
        hook) calls attach_print() which sets flags.in_print=True on the document
        without ever clearing it. This makes subsequent save() calls silently
        no-op (document.py:531). Clearing here ensures the document remains saveable.
        """
        self.flags.in_print = False
        self.flags.pop("print_settings", None)

    def set_application_status_defaults(self) -> "OperationResult[str]":
        """Set appropriate defaults for application_status based on member type - delegated to member_status_service

        Returns:
            OperationResult[str]: OperationResult with application_status on success
        """
        return set_member_application_status_defaults(self)

    def sync_status_fields(self) -> "OperationResult[dict]":
        """Ensure status and application_status fields are synchronized - delegated to member_status_service

        Returns:
            OperationResult[dict]: OperationResult with status fields on success
        """
        return sync_member_status_fields(self)

    def after_insert(self):
        """Execute after document is inserted"""
        if not self.customer and self.email:
            # Lazy import to avoid circular dependency
            from verenigingen.services.customer_handling_service import CustomerHandlingService

            customer_name = CustomerHandlingService().create_customer_for_member(
                self, suppress_messages=False
            )
            if customer_name:
                self.customer = customer_name
                # Security: Direct db_set required in after_insert hook.
                # After insert, in-memory changes don't persist - reload() would wipe them.
                # Using db_set() instead of save() avoids triggering validation hooks again.
                self.db_set("customer", customer_name, update_modified=False)

    def on_trash(self):
        """
        Handle cascade deletion of related records when a Member is deleted.

        EXTRACTED: Moved to MemberCleanupService.handle_member_deletion()
        for service layer separation.
        """
        from verenigingen.services.member.lifecycle.member_cleanup_service import get_member_cleanup_service

        return get_member_cleanup_service().handle_member_deletion(self)

    def _send_member_status_notification(self, old_status: str, new_status: str) -> None:
        """Send notification when member status changes.

        EXTRACTED: Moved to MemberStatusNotificationService.send_status_change_notification()
        for service layer separation.

        Args:
            old_status: Previous status value
            new_status: New status value
        """
        from verenigingen.services.member.lifecycle.member_status_notification_service import (
            get_member_status_notification_service,
        )

        get_member_status_notification_service().send_status_change_notification(self, old_status, new_status)

    def calculate_age(self):
        """Calculate age based on birth_date field - delegated to member_age_service"""
        update_member_age_field(self)

    def validate_age_requirements(self):
        """Validate age requirements for membership and volunteering - delegated to member_age_service"""
        validate_member_age_requirements(self)

    def calculate_total_membership_days(self):
        """Calculate total membership days from all active membership periods.

        Extracted to membership_duration_service for reusability. Delegates to the
        extracted service for consistent duration calculations.

        Returns:
            int: Total membership days, or 0 if calculation fails
        """
        return calculate_duration_days(self.name)

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.UTILITY)
    def update_membership_duration(self):
        """Update the total membership days and human-readable duration - delegates to MemberDurationService."""
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )

        return get_member_duration_service().update_duration(self)

    def generate_application_id(self):
        """Generate unique application ID - delegated to member_id_service"""
        return generate_application_id()

    def validate_name(self):
        """Validate that name fields don't contain special characters - delegated to dutch_name_service"""
        validate_member_name_fields(self)

    def update_full_name(self):
        """Update the full name based on first names, name particles (tussenvoegsels), and last name - delegated to dutch_name_service"""
        update_member_full_name(self)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.FINANCIAL)
    def create_customer(self) -> str:
        """Create a customer for this member in ERPNext - delegated to CustomerHandlingService"""
        # Lazy import to avoid circular dependency
        from verenigingen.services.customer_handling_service import CustomerHandlingService

        suppress_messages = getattr(self, "_suppress_customer_messages", False)
        customer_name = CustomerHandlingService().create_customer_for_member(self, suppress_messages)

        # Update member with customer reference if we got a customer name
        if customer_name:
            # Security: Direct db_set for simple reference link.
            # Full save() would trigger all validation hooks and update timestamps,
            # which is unnecessary for linking a reference and may conflict with
            # concurrent operations. Transaction commit handled by calling code.
            self.db_set("customer", customer_name, update_modified=False)
            self.customer = customer_name  # Keep in-memory object in sync

            # Only show success message if not during application submission
            if not suppress_messages:
                frappe.msgprint(_("Customer {0} created successfully").format(customer_name))

        return customer_name

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def create_user(self) -> Dict[str, Any]:
        """Create a user account for this member - delegates to MemberUserAccountService"""
        from verenigingen.services.member.account.member_user_account_service import (
            get_member_user_account_service,
        )

        return get_member_user_account_service().create_user_for_member(self)

    def handle_fee_override_changes(self):
        """
        Handle changes to membership fee override using amendment system with better atomicity.

        EXTRACTED: Moved to MemberFeeChangeService.handle_fee_override_changes()
        for service layer separation.
        """
        from verenigingen.services.member.core.member_fee_change_service import get_member_fee_change_service

        return get_member_fee_change_service().handle_fee_override_changes(self)

    def record_fee_change(self, change_data):
        """
        Record fee change in history using the financial history manager.

        EXTRACTED: Moved to MemberFeeChangeService.record_fee_change()
        for service layer separation.
        """
        from verenigingen.services.member.core.member_fee_change_service import get_member_fee_change_service

        return get_member_fee_change_service().record_fee_change(self, change_data)

    def get_active_membership(self):
        """
        Get the currently active membership for this member.

        EXTRACTED: Moved to MemberMembershipService.get_active_membership_for_member_doc()
        for service layer separation.

        Returns:
            Membership document if found, None otherwise
        """
        from verenigingen.services.member.core.member_membership_service import get_member_membership_service

        return get_member_membership_service().get_active_membership_for_member_doc(self)

    def update_membership_status(self):
        """Update member's membership_status field based on active memberships - delegated to member_status_service"""
        result = update_member_membership_status(self)
        if result:
            # Security: Direct db_set to prevent validation recursion.
            # This method is often called from validation hooks - using save()
            # would trigger validate() again, causing infinite recursion.
            # Transaction commit handled by calling code.
            self.db_set("membership_status", result, update_modified=False)
        return result

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.REPORTING)
    def get_other_members_at_address(self):
        """Get other members at same address - delegates to MemberAddressService."""
        return get_member_address_service().get_other_members_at_address_safe(self)

    def calculate_cumulative_membership_duration(self) -> None:
        """Calculate and set total membership duration - delegates to MemberDurationService."""
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )

        result = get_member_duration_service().calculate_cumulative_duration(self)
        return result.get("duration_years", 0)

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.ADMIN)
    def force_update_membership_duration(self):
        """Force update membership duration - delegates to MemberDurationService."""
        from verenigingen.services.member.utils.member_duration_service import (
            get_member_duration_service,
        )

        return get_member_duration_service().force_update_duration(self)

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.FINANCIAL)
    def get_current_membership_fee(self):
        """Get current effective membership fee - delegates to MemberFeeCalculationService"""
        from verenigingen.services.member.financial.member_fee_calculation_service import (
            get_member_fee_calculation_service,
        )

        return get_member_fee_calculation_service().get_current_membership_fee(self)

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.FINANCIAL)
    def get_display_membership_fee(self):
        """Get membership fee for display with amendment status - delegates to MemberFeeCalculationService"""
        from verenigingen.services.member.financial.member_fee_calculation_service import (
            get_member_fee_calculation_service,
        )

        return get_member_fee_calculation_service().get_display_membership_fee(self)

    def get_or_create_membership_item(self):
        """
        Get or create the membership fee item.

        EXTRACTED: Moved to MemberItemService.get_or_create_membership_item()
        for service layer separation (Member Phase 2E-1).
        """
        from verenigingen.services.member.financial.member_item_service import get_member_item_service

        return get_member_item_service().get_or_create_membership_item(self)

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.ADMIN)
    def force_update_chapter_display(self):
        """Force update chapter display - delegates to MemberChapterDisplayService."""
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )

        return get_member_chapter_display_service().force_update_chapter_display(self)

    def update_current_chapter_display(self):
        """Update chapter display field - delegates to MemberChapterDisplayService."""
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )

        return get_member_chapter_display_service().update_current_chapter_display(self)

    def get_current_chapters_optimized(self):
        """Get current chapters with optimized query - delegates to MemberChapterDisplayService."""
        from verenigingen.services.member.display.member_chapter_display_service import (
            get_member_chapter_display_service,
        )

        return get_member_chapter_display_service().get_current_chapters_optimized(self)

    def get_current_chapters(self):
        """Get current chapters - delegates to ChapterManagementService."""
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        return get_chapter_management_service().get_member_chapters(self.name)

    def update_other_members_at_address_display(self, save_to_db=False):
        """
        Update the other_members_at_address HTML field with data from get_other_members_at_address.

        EXTRACTED: HTML generation moved to MemberAddressDisplayService.update_other_members_at_address_display()
        Database save logic remains here for transaction control.
        """
        from verenigingen.services.member.display.member_address_display_service import (
            get_member_address_display_service,
        )

        # Generate HTML content using service
        html_content = get_member_address_display_service().update_other_members_at_address_display(self)

        # Set the HTML content
        self.other_members_at_address = html_content

        # Optionally save directly to database
        if save_to_db and not self.get("__islocal"):
            # Security: Direct db_set for display-only field update.
            # This is a computed HTML field that doesn't affect business logic.
            # Using db_set avoids unnecessary validation cycles.
            self.db_set("other_members_at_address", html_content, update_modified=False)

    def update_address_display(self):
        """
        Update the address_display HTML field with formatted address information.

        EXTRACTED: Moved to MemberAddressDisplayService.update_address_display()
        for service layer separation.
        """
        from verenigingen.services.member.display.member_address_display_service import (
            get_member_address_display_service,
        )

        self.address_display = get_member_address_display_service().update_address_display(self)

    def add_fee_change_to_history(self, schedule_data):
        """
        Add a single fee change to history incrementally.

        EXTRACTED: Moved to MemberFeeChangeHistoryService.add_fee_change_to_history()
        for service layer separation.
        """
        from verenigingen.services.member.history.member_fee_change_history_service import (
            get_member_fee_change_history_service,
        )

        return get_member_fee_change_history_service().add_fee_change_to_history(self, schedule_data)

    def update_fee_change_in_history(self, schedule_data):
        """
        Update an existing fee change in history.

        EXTRACTED: Moved to MemberFeeChangeHistoryService.update_fee_change_in_history()
        for service layer separation.
        """
        from verenigingen.services.member.history.member_fee_change_history_service import (
            get_member_fee_change_history_service,
        )

        return get_member_fee_change_history_service().update_fee_change_in_history(self, schedule_data)

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.ADMIN)
    def incremental_update_history_tables(self):
        """Rebuild payment history tables - delegates to MemberHistoryUpdateService"""
        from verenigingen.services.member.history.member_history_update_service import (
            get_member_history_update_service,
        )

        return get_member_history_update_service().incremental_update_history_tables(self)

    def _batch_fetch_with_chunking(self, doctype, name_list, fields, filters=None, chunk_size=500):
        """Fetch records in batches — delegates to shared utility."""
        from verenigingen.utils import batch_fetch_with_chunking

        return batch_fetch_with_chunking(doctype, name_list, fields, filters, chunk_size)

    def _get_volunteer_id(self):
        """Get the volunteer ID for this member"""
        try:
            return frappe.db.get_value("Volunteer", {"member": self.name}, "name")
        except Exception:
            return None


# Module-level functions for static calls


def _load_member_for_shim(doc, ptype):
    # Shim helper: resolves a Member doc passed by frappe.call("...member.<method>", doc=...).
    # JS uses frm.call('<method>'), which goes through Frappe's run_doc_method resolver and
    # never reaches these shims. The shims exist so dotted-path callers (tests, server scripts,
    # /api/method/<dotted.path>) can invoke whitelisted Member instance methods.
    #
    # Defense layering: this loader enforces DocPerm via check_permission(ptype). The wrapped
    # instance methods carry their own @critical_api/@high_security_api decorators that fire
    # the role-tier framework check when called. Stacking a framework decorator here too would
    # short-circuit at the role tier and mask the DocPerm-layer frappe.PermissionError that
    # callers (and tests) rely on.
    if not doc:
        frappe.throw(_("Member document required"))
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)
    name = doc.get("name") if isinstance(doc, dict) else None
    if not name:
        frappe.throw(_("Member name required"))
    member = frappe.get_doc("Member", name)
    member.check_permission(ptype)
    return member


@frappe.whitelist()
def create_customer(doc: str | dict = None):
    return _load_member_for_shim(doc, "write").create_customer()


@frappe.whitelist()
def create_user(doc: str | dict = None):
    return _load_member_for_shim(doc, "write").create_user()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_organization_user(
    member: str, email: str, first_name: str, last_name: str = "", send_welcome_email=True
):
    """Create an organization user account for a member.

    Backs the Member form's "Create Organization User Account" dialog, which
    supplies an org-domain email and name (distinct from the member's personal
    details). Delegates to MemberUserAccountService.
    """
    from verenigingen.services.member.account.member_user_account_service import (
        get_member_user_account_service,
    )

    member_doc = frappe.get_doc("Member", member)
    member_doc.check_permission("write")
    username, action = get_member_user_account_service().create_organization_user_for_member(
        member_doc,
        email=email,
        first_name=first_name,
        last_name=last_name,
        send_welcome_email=send_welcome_email,
    )
    return {"success": True, "user": username, "action": action}


@frappe.whitelist()
def update_membership_duration(doc: str | dict = None):
    return _load_member_for_shim(doc, "write").update_membership_duration()


@frappe.whitelist()
def get_address_members_html(doc: str | dict = None):
    return _load_member_for_shim(doc, "read").get_address_members_html()


@frappe.whitelist()
def get_current_membership_fee(doc: str | dict = None):
    return _load_member_for_shim(doc, "read").get_current_membership_fee()


@frappe.whitelist()
def get_display_membership_fee(doc: str | dict = None):
    return _load_member_for_shim(doc, "read").get_display_membership_fee()


@frappe.whitelist()
def ensure_member_id(doc: str | dict = None):
    # The instance method's @high_security_api decorator already converts the
    # underlying OperationResult to a dict (api_security_framework.py:934-939),
    # so this normally returns a dict already. The fallback below is defence in
    # depth: if the framework decorator is ever removed from the instance method
    # without compensating here, callers that re-serialise via stdlib json
    # (logging, debug, server scripts) would otherwise hit AttributeError.
    result = _load_member_for_shim(doc, "write").ensure_member_id()
    # callable(), not hasattr(): a frappe._dict has __getattr__ = dict.get, so
    # `result.to_dict` is None (not absent) and hasattr() would be True, making
    # `result.to_dict()` raise "'NoneType' object is not callable".
    to_dict = getattr(result, "to_dict", None)
    return to_dict() if callable(to_dict) else result


@frappe.whitelist()
@standard_api(operation_type=OperationType.PUBLIC)
def is_chapter_management_enabled():
    """Check if chapter management is enabled in settings"""
    from verenigingen.verenigingen.doctype.member.member_utils import (
        is_chapter_management_enabled as check_enabled,
    )

    return check_enabled()


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_board_memberships(member_name: str):
    """Get board memberships for a member"""
    from verenigingen.services.member.chapter import get_chapter_management_service

    return get_chapter_management_service().get_board_memberships(member_name)


def handle_fee_override_after_save(doc, method=None):
    """
    Hook function to handle fee override changes after save.

    EXTRACTED: Delegates to FeeOverrideHookService for processing.
    See services/member/financial/fee_override_hook_service.py for implementation.
    """
    from verenigingen.services.member.financial import handle_fee_override_after_save as _handle

    _handle(doc, method)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def assign_member_id(member_name: str):
    """Assign member ID - delegates to MemberIDService"""
    from verenigingen.services.member.identification.member_id_service import get_member_id_service

    return get_member_id_service().assign_member_id(member_name)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_volunteer_details_html_for_member(member_name: str) -> str:
    """Get volunteer details HTML for a specific member by name."""
    from verenigingen.services.member.display.member_volunteer_display_service import (
        get_member_volunteer_display_service,
    )

    member_doc = frappe.get_doc("Member", member_name)
    return get_member_volunteer_display_service().generate_volunteer_details_html(member_doc) or ""


# =============================================================================
# BACKWARD COMPATIBILITY RE-EXPORTS (TECH DEBT)
# =============================================================================
# Wildcard import for backward compatibility with code that imports from member.py.
# Re-exports moved to member_compat.py. Import from there or directly from api/member/.
#
# TODO(tech-debt): Track usage and remove once all callers updated to new import paths.
# See: verenigingen/api/member/ for the new canonical import locations.
from verenigingen.verenigingen.doctype.member.member_compat import *  # noqa: E402, F401, F403
