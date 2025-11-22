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

import random

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import date_diff, getdate, now, now_datetime, today

from verenigingen.services.customer_service import create_customer_for_member
from verenigingen.services.member.core.member_address_service import member_address_service
from verenigingen.services.member.core.member_id_service import generate_application_id, generate_member_id
from verenigingen.services.member.core.member_lifecycle_service import member_lifecycle_service
from verenigingen.services.member.core.member_status_service import (
    set_member_application_status_defaults,
    sync_member_status_fields,
    update_member_membership_status,
)
from verenigingen.services.member.utils.member_age_service import (
    get_age_group,
    update_member_age_field,
    validate_member_age_requirements,
)

# Extracted services
from verenigingen.services.member.utils.membership_duration_service import (
    calculate_total_membership_days as calculate_duration_days,
)
from verenigingen.services.member.utils.membership_duration_service import (
    format_duration_human_readable,
    update_member_duration_fields,
)
from verenigingen.utils.address_matching.dutch_address_normalizer import (
    AddressFingerprintCollisionHandler,
    DutchAddressNormalizer,
)
from verenigingen.utils.dutch_name_service import update_member_full_name, validate_member_name_fields
from verenigingen.utils.dutch_name_utils import (
    format_dutch_full_name,
    get_full_last_name,
    is_dutch_installation,
)
from verenigingen.utils.member_utils import get_active_membership_for_member, get_volunteer_for_member
from verenigingen.utils.safe_member_optimizer import safe_member_optimizer
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    development_only_api,
    high_security_api,
    standard_api,
)

# Migrated from old security_decorators to new api_security_framework
from verenigingen.verenigingen.doctype.member.member_id_manager import validate_member_id_change
from verenigingen.verenigingen.doctype.member.mixins.chapter_mixin import ChapterMixin
from verenigingen.verenigingen.doctype.member.mixins.expense_mixin import ExpenseMixin
from verenigingen.verenigingen.doctype.member.mixins.financial_mixin import FinancialMixin
from verenigingen.verenigingen.doctype.member.mixins.payment_mixin import PaymentMixin
from verenigingen.verenigingen.doctype.member.mixins.sepa_mixin import SEPAMandateMixin
from verenigingen.verenigingen.doctype.member.mixins.termination_mixin import TerminationMixin


def generate_volunteer_details_html(member_doc):
    """
    Generate HTML display for volunteer details and assignment history.

    EXTRACTED: Moved to MemberVolunteerDisplayService.generate_volunteer_details_html()
    for service layer separation.

    Args:
        member_doc: Member document instance

    Returns:
        str: Formatted HTML string with volunteer details and assignment history
    """
    from verenigingen.services.member.display.member_volunteer_display_service import (
        MemberVolunteerDisplayService,
    )

    return MemberVolunteerDisplayService.generate_volunteer_details_html(member_doc)


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

    def before_save(self):
        """Execute before saving the document with optimized performance.

        Performs necessary field updates and validations before saving,
        with performance optimizations to avoid unnecessary processing.

        Operations:
            1. Safe performance optimization (metadata caching, link batching)
            2. Member/Application ID generation (conditional)
            3. Chapter display updates (when needed)
            4. Address normalization (when address changes)
            5. Application status defaults
            6. Counter reset handling

        Performance Features:
            - Safe metadata caching and query batching
            - Change detection to avoid unnecessary updates
            - Conditional processing based on field changes
            - Efficient address fingerprinting
            - Minimal database queries
        """
        # Apply safe performance optimizations if enabled
        try:
            safe_member_optimizer.optimize_member_creation(self)
        except Exception as e:
            # Log but don't fail member creation if optimization fails
            frappe.log_error(
                f"Safe member optimization failed for {self.name}: {str(e)}", "Member Before Save"
            )
        # Generate appropriate IDs based on member status
        # Member IDs are only assigned to approved members to prevent premature ID allocation
        if not self.member_id:
            if self.should_have_member_id():
                frappe.logger().info(
                    f"Generating member ID for {self.name} - application_status: {getattr(self, 'application_status', 'None')}, is_application: {self.is_application_member()}"
                )
                self.member_id = generate_member_id()
                frappe.logger().info(f"Generated member ID: {self.member_id} for {self.name}")
            elif self.is_application_member() and not self.application_id:
                # Assign application ID for tracking pending applications
                self.application_id = None
                self.application_id = generate_application_id()
        else:
            frappe.logger().debug(f"Member {self.name} already has member_id: {self.member_id}")

        # Update chapter display only when necessary to optimize performance
        # This prevents unnecessary geographic lookups and database queries
        if self._should_update_chapter_display():
            self.update_current_chapter_display()

        # Update computed address fields for efficient member matching
        # This creates normalized fingerprints for duplicate detection
        self._update_computed_address_fields()

        # Clear counter reset flag after processing to prevent repeated resets
        if hasattr(self, "reset_counter_to") and self.reset_counter_to:
            self.reset_counter_to = None
            self.reset_counter_to = None

        # Ensure application status is properly set based on member state
        set_member_application_status_defaults(self)

    def _should_update_chapter_display(self):
        """
        Check if chapter display needs updating to avoid unnecessary processing.

        EXTRACTED: Moved to MemberChapterDisplayService.should_update_chapter_display()
        for service layer separation (Phase 2D-3).
        """
        from verenigingen.services.member.display.member_chapter_display_service import (
            MemberChapterDisplayService,
        )

        return MemberChapterDisplayService.should_update_chapter_display(self)

    def _update_computed_address_fields(self):
        """Update computed address fields using Address Management Service.

        Delegates to member_address_service for consistent address processing
        with improved error handling and performance optimization.

        Features:
            - Dutch address normalization via service
            - Address fingerprinting with collision handling
            - Change detection to avoid unnecessary processing
            - Comprehensive error handling and logging

        Side Effects:
            - Updates address_fingerprint field
            - Updates normalized_address_line field
            - Updates normalized_city field
            - Sets address_last_updated timestamp
        """
        try:
            result = member_address_service.update_member_address_fields(self)

            if not result["success"]:
                # Log errors from the service
                for error in result["errors"]:
                    frappe.log_error(error, "Member Address Update")

                # Log warnings if any
                for warning in result["warnings"]:
                    frappe.logger().warning(warning)

        except Exception as e:
            frappe.log_error(
                f"Error calling address service for {self.name}: {str(e)}", "Member Address Service"
            )

    def _validate_fee_override_amount(self, amount):
        """
        Validate fee override amount is positive.

        EXTRACTED: Moved to MemberFeeValidationService.validate_fee_override_amount()
        for service layer separation (Phase 2D-2).
        """
        from verenigingen.services.member.financial.member_fee_validation_service import (
            MemberFeeValidationService,
        )

        MemberFeeValidationService.validate_fee_override_amount(amount)

    def _validate_fee_override_reason(self):
        """
        Validate fee override has documented reason when required.

        EXTRACTED: Moved to MemberFeeValidationService.validate_fee_override_reason()
        for service layer separation (Phase 2D-2).
        """
        from verenigingen.services.member.financial.member_fee_validation_service import (
            MemberFeeValidationService,
        )

        MemberFeeValidationService.validate_fee_override_reason(self)

    def validate_fee_override_permissions(self):
        """
        Validate that only authorized users can set fee overrides.

        EXTRACTED: Moved to MemberFeeValidationService.validate_fee_override_permissions()
        for service layer separation (Phase 2D-2).
        """
        from verenigingen.services.member.financial.member_fee_validation_service import (
            MemberFeeValidationService,
        )

        MemberFeeValidationService.validate_fee_override_permissions(self)

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
        admin_roles = ["System Manager", "Verenigingen Staff", "Verenigingen Administrator"]
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
    def get_address_members_html(self):
        """Get HTML content for address members field - delegates to MemberAddressDisplayService"""
        from verenigingen.services.member.display.member_address_display_service import (
            MemberAddressDisplayService,
        )

        return MemberAddressDisplayService.get_address_members_html(self)

    def _get_status_color(self, status):
        """Get Bootstrap color class for member status - delegated to member_status_service"""
        from verenigingen.services.member.core.member_status_service import get_member_status_color

        return get_member_status_color(status)

    @frappe.whitelist()
    @development_only_api(operation_type=OperationType.UTILITY)
    def after_save(self):
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
        from verenigingen.services.member.account.member_user_account_service import MemberUserAccountService

        MemberUserAccountService.create_user_account_if_needed(self)

    def onload(self):
        """Execute when document is loaded"""
        try:
            # Update chapter display when form loads
            if not self.get("__islocal"):
                try:
                    self.update_current_chapter_display()
                except Exception as e:
                    frappe.log_error(f"Error updating chapter display in onload for {self.name}: {e}")

                try:
                    # Update address display
                    self.update_address_display()
                except Exception as e:
                    frappe.log_error(f"Error updating address display in onload for {self.name}: {e}")

                try:
                    # Update other members at address display
                    # This may fail for users with limited permissions - that's acceptable
                    self.update_other_members_at_address_display()
                    # Ensure the HTML field is included in the response
                    if hasattr(self, "other_members_at_address") and self.other_members_at_address:
                        self.set_onload("other_members_at_address", self.other_members_at_address)
                except Exception as e:
                    # Silently handle permission errors - household members display is non-critical
                    # Only log if it's not a permission error
                    error_str = str(e)
                    if "Access denied" not in error_str and "permission" not in error_str.lower():
                        frappe.log_error(
                            f"Error updating other members at address display in onload for {self.name}: {e}"
                        )
                    # Clear the field to prevent showing stale data
                    self.other_members_at_address = ""

                try:
                    # Update volunteer details HTML with assignment history
                    html = generate_volunteer_details_html(self)
                    if html:
                        self.volunteer_details_html = html
                        # Pass HTML to client via onload (same pattern as other_members_at_address)
                        self.set_onload("volunteer_details_html", html)
                except Exception as e:
                    frappe.log_error(f"Error loading volunteer details HTML in onload for {self.name}: {e}")

                try:
                    # Calculate membership duration on-demand from Membership records
                    self.calculate_cumulative_membership_duration()
                except Exception as e:
                    frappe.log_error(f"Error calculating membership duration in onload for {self.name}: {e}")

        except Exception as e:
            frappe.log_error(f"Critical error in onload method for {self.name}: {e}")
            # Don't raise exception to prevent form loading issues

    def is_application_member(self):
        """Check if this member was created through the application process"""
        return member_lifecycle_service.is_application_member(self)

    def should_have_member_id(self):
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
    def ensure_member_id(self):
        """Ensure this member has a member ID if they should have one - delegated to member_id_service"""
        from verenigingen.services.member.core.member_id_service import ensure_member_has_id

        return ensure_member_has_id(self)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def force_assign_member_id(self):
        """Force assign a member ID regardless of normal rules (admin only) - delegated to member_id_service"""
        from verenigingen.services.member.core.member_id_service import force_assign_member_id

        return force_assign_member_id(self)

    def _guess_relationship(self, other_member):
        """
        Attempt to guess relationship based on name patterns and data.

        EXTRACTED: Moved to MemberAddressService.guess_relationship()
        for service layer separation and better testability.
        """
        from verenigingen.services.member.core.member_address_service import member_address_service

        return member_address_service.guess_relationship(self, other_member)

    def _get_age_group(self, birth_date):
        """Get age group for privacy-friendly display - delegated to member_age_service"""
        return get_age_group(birth_date)

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def approve_application(self):
        """Approve this application and assign member ID"""
        # Use lifecycle service for core approval logic
        result = member_lifecycle_service.approve_application(self)

        if not result["success"]:
            # If there are errors, throw the first one
            if result["errors"]:
                frappe.throw(_(result["errors"][0]))
            else:
                frappe.throw(_("Application approval failed"))

        # Create membership - this should trigger the dues schedule logic
        return self.create_membership_on_approval()

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

        return MembershipCreationService.create_membership_on_approval(
            self,
            start_date=start_date,
            create_invoice=create_invoice,
            custom_dues_rate=custom_dues_rate,
            custom_rate_reason=custom_rate_reason,
            is_csv_import=is_csv_import,
            approval_fields=approval_fields,
        )

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def reject_application(self, reason):
        """Reject this application and clean up pending records"""
        # Use lifecycle service for core rejection logic
        result = member_lifecycle_service.reject_application(self, reason)

        if not result["success"]:
            # If there are errors, throw the first one
            if result["errors"]:
                frappe.throw(_(result["errors"][0]))
            else:
                frappe.throw(_("Application rejection failed"))

        frappe.logger().info(f"Rejected application for {self.name}")
        return True

    def validate(self):
        """Validate document data with optional performance optimizations"""
        # Note: Initial IBAN history for directly created members should be handled manually
        # after creation, or through the application approval process for application members

        # Core validations (always required)
        validate_member_name_fields(self)
        update_member_full_name(self)
        update_member_membership_status(self)
        update_member_age_field(self)
        validate_member_age_requirements(self)  # Add age validation

        # Only calculate duration if explicitly requested or if this is a new member
        # Daily scheduler handles routine duration updates to avoid on-visit field changes
        if getattr(self, "_force_duration_update", False) or self.is_new():
            self.calculate_cumulative_membership_duration()

        # Payment and business validations (optimized if possible)
        self.validate_payment_method()
        self.set_payment_reference()
        self.validate_bank_details()

        # Member ID validation
        validate_member_id_change(self)
        self.handle_fee_override_changes()
        sync_member_status_fields(self)

        # Clear application_status once member leaves application workflow
        # Application workflow states are: Pending, Under Review, Approved, Rejected, Payment Pending
        # Once member becomes Active, Terminated, Suspended, etc., application_status is no longer relevant
        if self.status not in ["Pending"] and self.application_status in [
            "Pending",
            "Under Review",
            "Approved",
            "Rejected",
            "Payment Pending",
        ]:
            self.application_status = None

    def on_update(self):
        """Emit events for status changes to trigger background operations"""
        try:
            # Skip event emission during bulk operations or tests
            if getattr(frappe.flags, "bulk_member_operations", False) or getattr(
                frappe.flags, "in_test", False
            ):
                return

            # Import here to avoid circular dependencies
            from verenigingen.events.member_events import (
                emit_member_lifecycle_changed,
                emit_member_status_changed,
            )

            # Track application status changes (Pending -> Approved workflow)
            if self.has_value_changed("application_status"):
                old_status = self.get_db_value("application_status")
                new_status = self.application_status

                frappe.logger().info(
                    f"Member {self.name} application status changed: {old_status} -> {new_status}"
                )

                emit_member_status_changed(
                    self.name,
                    {"old_status": old_status, "new_status": new_status, "status_type": "application"},
                )

            # Track general member status changes (Active, Suspended, Terminated)
            if self.has_value_changed("status"):
                old_status = self.get_db_value("status")
                new_status = self.status

                frappe.logger().info(f"Member {self.name} status changed: {old_status} -> {new_status}")

                emit_member_lifecycle_changed(
                    self.name,
                    {"old_status": old_status, "new_status": new_status, "status_type": "membership"},
                )

            # Bidirectional sync removed - Chapter and Volunteer are sources of truth
            # Member displays this data read-only (editable only for Verenigingen Staff/Administrator)

        except Exception as e:
            # Event emission should never block member updates
            frappe.log_error(
                f"Failed to emit member events for {self.name}: {str(e)}", "Member Event Emission Error"
            )

    def set_application_status_defaults(self):
        """Set appropriate defaults for application_status based on member type - delegated to member_status_service"""
        return set_member_application_status_defaults(self)

    def sync_status_fields(self):
        """Ensure status and application_status fields are synchronized - delegated to member_status_service"""
        return sync_member_status_fields(self)

    def after_insert(self):
        """Execute after document is inserted"""
        if not self.customer and self.email:
            customer_name = create_customer_for_member(self, suppress_messages=False)
            self.customer = customer_name
            # CRITICAL: Must save to persist customer link to database
            # Otherwise reload() will wipe out this in-memory value
            frappe.db.set_value("Member", self.name, "customer", customer_name, update_modified=False)
            frappe.db.commit()

    def on_trash(self):
        """
        Handle cascade deletion of related records when a Member is deleted.

        EXTRACTED: Moved to MemberCleanupService.handle_member_deletion()
        for service layer separation.
        """
        from verenigingen.services.member.lifecycle.member_cleanup_service import MemberCleanupService

        return MemberCleanupService.handle_member_deletion(self)

    def _unlink_from_customer(self):
        """
        Remove Member link from Customer's Dynamic Links table.

        EXTRACTED: Moved to MemberCleanupService._unlink_member_from_customer()
        for service layer separation.
        """
        from verenigingen.services.member.lifecycle.member_cleanup_service import MemberCleanupService

        return MemberCleanupService._unlink_member_from_customer(self)

    def _unlink_from_address(self, address_name):
        """
        Remove Member link from Address's links table.

        EXTRACTED: Moved to MemberCleanupService._unlink_member_from_address()
        for service layer separation.
        """
        from verenigingen.services.member.lifecycle.member_cleanup_service import MemberCleanupService

        return MemberCleanupService._unlink_member_from_address(self, address_name)

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
        """Update the total membership days and human-readable duration.

        Extracted to membership_duration_service for reusability. Delegates to the
        extracted service for consistent duration updates.

        Returns:
            dict: Result with success status and calculated values
        """
        try:
            # Use extracted service to update duration fields
            result = update_member_duration_fields(self)

            if result["success"]:
                # Suppress version tracking for automatic duration updates
                # These are calculated fields updated by scheduler, not user actions
                self.flags.ignore_version = True
                # Save the record - proper validation maintained
                self.save()

            return result

        except Exception as e:
            frappe.log_error(f"Error updating membership duration for {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}

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
    def create_customer(self):
        """Create a customer for this member in ERPNext - delegated to customer_service"""
        suppress_messages = getattr(self, "_suppress_customer_messages", False)
        customer_name = create_customer_for_member(self, suppress_messages)

        # Update member with customer reference if we got a customer name
        if customer_name:
            # Update database directly to avoid validation/timestamp conflicts
            frappe.db.set_value("Member", self.name, "customer", customer_name)
            self.customer = customer_name  # Update the document object too
            frappe.db.commit()

            # Only show success message if not during application submission
            if not suppress_messages:
                frappe.msgprint(_("Customer {0} created successfully").format(customer_name))

        return customer_name

    @frappe.whitelist()
    @critical_api(operation_type=OperationType.ADMIN)
    def create_user(self):
        """Create a user account for this member - delegates to MemberUserAccountService"""
        from verenigingen.services.member.account.member_user_account_service import MemberUserAccountService

        return MemberUserAccountService.create_user_for_member(self)

    def handle_fee_override_changes(self):
        """
        Handle changes to membership fee override using amendment system with better atomicity.

        EXTRACTED: Moved to MemberFeeChangeService.handle_fee_override_changes()
        for service layer separation.
        """
        from verenigingen.services.member.core.member_fee_change_service import MemberFeeChangeService

        return MemberFeeChangeService.handle_fee_override_changes(self)

    def record_fee_change(self, change_data):
        """
        Record fee change in history using the financial history manager.

        EXTRACTED: Moved to MemberFeeChangeService.record_fee_change()
        for service layer separation.
        """
        from verenigingen.services.member.core.member_fee_change_service import MemberFeeChangeService

        return MemberFeeChangeService.record_fee_change(self, change_data)

    def get_active_membership(self):
        """
        Get the currently active membership for this member.

        EXTRACTED: Moved to MemberMembershipService.get_active_membership_for_member_doc()
        for service layer separation.

        Returns:
            Membership document if found, None otherwise
        """
        from verenigingen.services.member.core.member_membership_service import MemberMembershipService

        return MemberMembershipService.get_active_membership_for_member_doc(self)

    def update_membership_status(self):
        """Update member's membership_status field based on active memberships - delegated to member_status_service"""
        result = update_member_membership_status(self)
        if result:
            # Update database directly to avoid validation recursion
            frappe.db.set_value("Member", self.name, "membership_status", result)
            frappe.db.commit()
        return result

    @frappe.whitelist()
    @development_only_api(operation_type=OperationType.UTILITY)
    def debug_address_detection(self):
        """Debug the address detection functionality for troubleshooting"""
        try:
            result = {
                "member_name": self.full_name,
                "primary_address": self.primary_address,
                "has_primary_address": bool(self.primary_address),
            }

            if self.primary_address:
                # Get address details
                address_doc = frappe.get_doc("Address", self.primary_address)
                result["address_details"] = {
                    "name": address_doc.name,
                    "address_line1": address_doc.address_line1,
                    "city": address_doc.city,
                }

                # Call the address detection method
                try:
                    address_result = self.get_other_members_at_address()
                    result["address_detection_result"] = address_result
                    result["address_detection_type"] = type(address_result).__name__
                    result["address_detection_length"] = (
                        len(address_result) if isinstance(address_result, (list, str)) else "N/A"
                    )
                except Exception as e:
                    result["address_detection_error"] = str(e)

            return result

        except Exception as e:
            return {"error": str(e)}

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.REPORTING)
    def get_other_members_at_address(self):
        """Get other members living at the same address using Address Management Service"""
        try:
            frappe.logger().info(
                f"get_other_members_at_address called for {self.name} with address {self.primary_address}"
            )

            result = member_address_service.get_colocated_members(self)

            if not result["success"]:
                # Log errors from the service
                for error in result["errors"]:
                    frappe.log_error(error, "Get Colocated Members")

                # Return empty list to ensure valid JSON response
                return []

            # Log warnings if any
            for warning in result["warnings"]:
                frappe.logger().warning(warning)

            frappe.logger().info(
                f"Found {result['count']} other members for {self.name} using address service"
            )
            return result["members"]

        except Exception as e:
            frappe.log_error(f"Error calling address service for {self.name}: {str(e)}")
            # Return empty list to ensure valid JSON response
            return []

    def calculate_cumulative_membership_duration(self):
        """Calculate and set total membership duration in human-readable format.

        Calculates duration on-demand from Membership records (start_date, cancellation_date).
        No stored day counter - always calculates fresh from source data.

        Returns:
            float: Duration in years for backward compatibility
        """
        try:
            # Always calculate fresh from Membership records
            total_days = self.calculate_total_membership_days()

            # Use extracted service for formatting (rounded to months)
            self.cumulative_membership_duration = format_duration_human_readable(total_days)

            # Return the value in years for backward compatibility
            return total_days / 365.25 if total_days > 0 else 0

        except Exception as e:
            frappe.log_error(
                f"Error calculating cumulative membership duration for {self.name}: {str(e)}", "Member Error"
            )
            self.cumulative_membership_duration = "Error calculating duration"
            return 0

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.ADMIN)
    def force_update_membership_duration(self):
        """Force update membership duration - can be called manually to update the field"""
        try:
            self._force_duration_update = True
            self.calculate_cumulative_membership_duration()
            # Save with minimal logging to avoid activity log entries
            self.flags.ignore_version = True
            self.flags.ignore_links = True
            # Force update method: only bypass after-submit validation for analytics fields
            self.flags.ignore_validate_update_after_submit = True  # JUSTIFIED: Analytics update only
            self.save()  # FIXED: Removed inappropriate permission bypass
            return {
                "success": True,
                "duration": self.cumulative_membership_duration,
                "message": "Membership duration updated successfully",
            }
        except Exception as e:
            frappe.log_error(f"Error force updating membership duration for {self.name}: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            # Clear the flag
            if hasattr(self, "_force_duration_update"):
                delattr(self, "_force_duration_update")

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.FINANCIAL)
    def get_current_membership_fee(self):
        """Get current effective membership fee - delegates to MemberFeeCalculationService"""
        from verenigingen.services.member.financial.member_fee_calculation_service import (
            MemberFeeCalculationService,
        )

        return MemberFeeCalculationService.get_current_membership_fee(self)

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.FINANCIAL)
    def get_display_membership_fee(self):
        """Get membership fee for display with amendment status - delegates to MemberFeeCalculationService"""
        from verenigingen.services.member.financial.member_fee_calculation_service import (
            MemberFeeCalculationService,
        )

        return MemberFeeCalculationService.get_display_membership_fee(self)

    def get_or_create_membership_item(self):
        """Get or create the membership fee item"""
        try:
            item_code = "MEMBERSHIP-FEE"

            existing_item = frappe.db.exists("Item", item_code)
            if existing_item:
                return frappe.get_doc("Item", existing_item)

            # Create membership fee item
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": "Membership Fee",
                    "item_group": self._get_default_item_group(),
                    "is_service_item": 1,
                    "maintain_stock": 0,
                    "include_item_in_manufacturing": 0,
                    "is_purchase_item": 0,
                    "is_sales_item": 1,
                }
            )

            item_result = secure_document_operation(
                operation="insert",
                doc=item,
                justification=f"Automated membership item creation for member {self.name}",
                required_permissions=["Item:create"],
            )

            if not item_result.success:
                frappe.logger().error(f"Failed to create membership item: {'; '.join(item_result.errors)}")
                return None
            frappe.logger().info(f"Created membership item {item.name}")
            return item

        except Exception as e:
            frappe.log_error(f"Error creating membership item: {str(e)}")
            return None

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.ADMIN)
    def force_update_chapter_display(self):
        """Force update chapter display - useful for fixing display issues"""
        self._chapter_assignment_in_progress = True
        self.update_current_chapter_display()
        self.save()  # FIXED: Removed inappropriate permission bypass
        return {
            "success": True,
            "message": "Chapter display updated",
            "current_chapter_display": getattr(self, "current_chapter_display", "Not set"),
        }

    @frappe.whitelist()
    @development_only_api(operation_type=OperationType.UTILITY)
    def debug_chapter_assignment(self):
        """Debug chapter assignment for this member"""
        # Check chapter memberships in Chapter Member table
        chapter_members = frappe.get_all(
            "Chapter Member",
            filters={"member": self.name, "enabled": 1},
            fields=["parent as chapter", "chapter_join_date", "enabled"],
            order_by="chapter_join_date desc",
        )

        # Check board memberships
        # First get volunteer record for this member
        volunteer = get_volunteer_for_member(self.name)
        board_members = []
        if volunteer:
            board_members = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer, "is_active": 1},
                fields=["parent as chapter", "chapter_role", "is_active"],
            )

        # Check current chapter display
        current_chapter_display = getattr(self, "current_chapter_display", "Not set")

        # Get optimized chapters
        try:
            optimized_chapters = self.get_current_chapters_optimized()
        except Exception as e:
            optimized_chapters = f"Error: {str(e)}"

        return {
            "member_name": self.full_name,
            "member_id": self.name,
            "chapter_members": chapter_members,
            "board_members": board_members,
            "current_chapter_display": current_chapter_display,
            "optimized_chapters": optimized_chapters,
            "chapter_management_enabled": frappe.db.get_single_value(
                "Verenigingen Settings", "enable_chapter_management"
            ),
        }

    def update_current_chapter_display(self):
        """
        Update the current chapter display field with formatted HTML.

        EXTRACTED: Moved to MemberChapterDisplayService.update_current_chapter_display()
        for service layer separation.
        """
        from verenigingen.services.member.display.member_chapter_display_service import (
            MemberChapterDisplayService,
        )

        return MemberChapterDisplayService.update_current_chapter_display(self)

    def get_current_chapters_optimized(self):
        """
        Get current chapter memberships with optimized single query.

        Delegates to ChapterManagementService for optimized query execution.
        This method is maintained for backward compatibility but delegates to service.
        """
        if not self.name:
            return []

        try:
            from verenigingen.services.member.chapter.chapter_management_service import (
                ChapterManagementService,
            )

            return ChapterManagementService.get_member_chapters_optimized(self.name)
        except Exception as e:
            frappe.log_error(f"Error getting current chapters optimized: {str(e)}", "Member Chapter Query")
            # Fallback to original method
            return self.get_current_chapters()

    def get_current_chapters(self):
        """Get current chapter memberships from Chapter Member child table (fallback method)"""
        if not self.name:
            return []

        try:
            # Get chapters where this member is listed in the Chapter Member child table
            # Query within member context - permissions should be respected
            # Include both Active and Pending memberships to show complete picture
            chapter_members = frappe.get_all(
                "Chapter Member",
                filters={"member": self.name, "enabled": 1},
                fields=["parent", "chapter_join_date", "status"],
                order_by="chapter_join_date desc",
                # FIXED: Removed inappropriate permission bypass
            )

            chapters = []
            for cm in chapter_members:
                chapters.append(
                    {
                        "chapter": cm.parent,
                        "chapter_join_date": cm.chapter_join_date,
                        "status": cm.status,
                        "is_primary": len(chapters) == 0,  # First one is primary
                        "is_board": self.is_board_member(cm.parent),
                    }
                )

            return chapters

        except Exception as e:
            frappe.log_error(f"Error getting current chapters: {str(e)}", "Member Chapter Query")
            return []

    def update_other_members_at_address_display(self, save_to_db=False):
        """
        Update the other_members_at_address HTML field with data from get_other_members_at_address.

        EXTRACTED: HTML generation moved to MemberAddressDisplayService.update_other_members_at_address_display()
        Database save logic remains here for transaction control.
        """
        from verenigingen.services.member.display.member_address_display_service import (
            MemberAddressDisplayService,
        )

        # Generate HTML content using service
        html_content = MemberAddressDisplayService.update_other_members_at_address_display(self)

        # Set the HTML content
        self.other_members_at_address = html_content

        # Optionally save directly to database
        if save_to_db and not self.get("__islocal"):
            frappe.db.set_value("Member", self.name, "other_members_at_address", html_content)
            frappe.db.commit()

    def update_address_display(self):
        """
        Update the address_display HTML field with formatted address information.

        EXTRACTED: Moved to MemberAddressDisplayService.update_address_display()
        for service layer separation.
        """
        from verenigingen.services.member.display.member_address_display_service import (
            MemberAddressDisplayService,
        )

        self.address_display = MemberAddressDisplayService.update_address_display(self)

    def add_fee_change_to_history(self, schedule_data):
        """
        Add a single fee change to history incrementally.

        EXTRACTED: Moved to MemberFeeChangeHistoryService.add_fee_change_to_history()
        for service layer separation.
        """
        from verenigingen.services.member.history.member_fee_change_history_service import (
            MemberFeeChangeHistoryService,
        )

        return MemberFeeChangeHistoryService.add_fee_change_to_history(self, schedule_data)

    def update_fee_change_in_history(self, schedule_data):
        """
        Update an existing fee change in history.

        EXTRACTED: Moved to MemberFeeChangeHistoryService.update_fee_change_in_history()
        for service layer separation.
        """
        from verenigingen.services.member.history.member_fee_change_history_service import (
            MemberFeeChangeHistoryService,
        )

        return MemberFeeChangeHistoryService.update_fee_change_in_history(self, schedule_data)

    def _update_donation_history(self):
        """Update donation history for this member - delegates to DonationHistoryManager"""
        if not (hasattr(self, "donor") and self.donor):
            return 0

        from verenigingen.utils.donation_history_manager import sync_donor_history

        # Sync uses the proper manager - check if it made changes
        original_donation_count = len(getattr(self, "donation_history", []))
        sync_donor_history(self.donor)
        # Reload to get updated donation history
        self.reload()
        new_donation_count = len(getattr(self, "donation_history", []))
        return abs(new_donation_count - original_donation_count)

    def _update_volunteer_expense_history(self):
        """Update volunteer expense history - delegates to MemberHistoryUpdateService"""
        from verenigingen.services.member.history.member_history_update_service import (
            MemberHistoryUpdateService,
        )

        return MemberHistoryUpdateService._update_volunteer_expense_history(self)

    def _update_dues_payment_history(self):
        """Rebuild membership dues payment history - delegates to MemberHistoryUpdateService"""
        from verenigingen.services.member.history.member_history_update_service import (
            MemberHistoryUpdateService,
        )

        return MemberHistoryUpdateService._update_dues_payment_history(self)

    def _update_invoice_payment_history(self):
        """Rebuild membership invoice payment history - delegates to MemberHistoryUpdateService"""
        from verenigingen.services.member.history.member_history_update_service import (
            MemberHistoryUpdateService,
        )

        return MemberHistoryUpdateService._update_invoice_payment_history(self)

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.ADMIN)
    def incremental_update_history_tables(self):
        """Rebuild payment history tables - delegates to MemberHistoryUpdateService"""
        from verenigingen.services.member.history.member_history_update_service import (
            MemberHistoryUpdateService,
        )

        return MemberHistoryUpdateService.incremental_update_history_tables(self)

    def _batch_fetch_with_chunking(self, doctype, name_list, fields, filters=None, chunk_size=500):
        """
        Fetch records in batches - delegates to MemberHistoryUpdateService.

        EXTRACTED: This method has been moved to MemberHistoryUpdateService._batch_fetch_with_chunking()
        for better service layer separation and reusability.
        """
        from verenigingen.services.member.history.member_history_update_service import (
            MemberHistoryUpdateService,
        )

        return MemberHistoryUpdateService._batch_fetch_with_chunking(
            doctype, name_list, fields, filters, chunk_size
        )

    def _build_expense_entries_batched(self, claims):
        """
        Build expense entries - delegates to MemberHistoryUpdateService.

        EXTRACTED: Moved to MemberHistoryUpdateService._build_expense_entries_batched()
        for service layer separation. Query reduction: 41 queries → 3 queries (93%).
        """
        from verenigingen.services.member.history.member_history_update_service import (
            MemberHistoryUpdateService,
        )

        return MemberHistoryUpdateService._build_expense_entries_batched(self, claims)

    def _build_lightweight_expense_entry(self, claim_data):
        """
        Build expense entry - delegates to MemberHistoryUpdateService.

        EXTRACTED: Moved to MemberHistoryUpdateService._build_lightweight_expense_entry()
        for service layer separation.
        """
        from verenigingen.services.member.history.member_history_update_service import (
            MemberHistoryUpdateService,
        )

        return MemberHistoryUpdateService._build_lightweight_expense_entry(self, claim_data)

    def _get_volunteer_id(self):
        """Get the volunteer ID for this member"""
        try:
            return frappe.db.get_value("Volunteer", {"member": self.name}, "name")
        except Exception:
            return None


# Module-level functions for static calls


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
def get_board_memberships(member_name):
    """Get board memberships for a member"""
    from verenigingen.services.member.chapter import ChapterManagementService

    return ChapterManagementService.get_board_memberships(member_name)


def handle_fee_override_after_save(doc, method=None):
    """Hook function to handle fee override changes after save with improved atomicity"""
    frappe.logger().info(f"handle_fee_override_after_save called for member {doc.name}, method={method}")

    # Skip fee change processing during bulk operations - rates are set directly on dues schedules
    # This avoids deadlocks from concurrent amendment processing during bulk imports
    bulk_flag = getattr(frappe.flags, "bulk_member_operations", False)
    csv_flag = getattr(doc, "_csv_import", False)
    system_update_flag = getattr(doc, "_system_update", False)
    # CRITICAL: Also check persistent tracking set (survives document reloads)
    in_bulk_import = (
        hasattr(frappe.local, "bulk_import_members") and doc.name in frappe.local.bulk_import_members
    )

    frappe.logger().info(
        f"[FEE OVERRIDE HOOK] Called for {doc.name}, "
        f"bulk_flag={bulk_flag}, csv_flag={csv_flag}, "
        f"system_flag={system_update_flag}, in_bulk_import={in_bulk_import}"
    )
    if bulk_flag or csv_flag or system_update_flag or in_bulk_import:
        frappe.logger().info(f"[FEE OVERRIDE HOOK] Skipping for {doc.name} - bulk operation in progress")
        return

    # Handle deferred fee changes
    if hasattr(doc, "_pending_fee_change"):
        try:
            frappe.logger().info(f"Processing pending fee change for member {doc.name}")

            # Use separate database transaction for fee change processing
            frappe.db.begin()
            try:
                # Create amendment request
                try:
                    from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
                        create_fee_change_amendment,
                    )

                    amendment = create_fee_change_amendment(
                        member_name=doc.name,
                        new_amount=doc._pending_fee_change["new_amount"],
                        reason=doc._pending_fee_change["reason"],
                    )

                    dues_schedule_action = f"Amendment request created: {amendment.name}"

                except Exception as e:
                    frappe.logger().warning(f"Could not create amendment request: {str(e)}")
                    dues_schedule_action = "Amendment creation failed, direct dues schedule update"

                # Record the change in history (using direct SQL to avoid recursion)
                history_entry = {
                    "change_date": doc._pending_fee_change["change_date"],
                    "old_amount": doc._pending_fee_change["old_amount"],
                    "new_amount": doc._pending_fee_change["new_amount"],
                    "reason": doc._pending_fee_change["reason"],
                    "changed_by": doc._pending_fee_change["changed_by"],
                    "dues_schedule_action": dues_schedule_action,
                }

                # Get current fee change history
                # Get current fee change history with safe parsing
                current_history = frappe.db.get_value("Member", doc.name, "fee_change_history")
                if not current_history or current_history.strip() == "":
                    history_list = []
                else:
                    try:
                        history_list = frappe.parse_json(current_history)
                        if not isinstance(history_list, list):
                            frappe.log_error(
                                f"Invalid fee_change_history format for member {doc.name}: {type(history_list)}",
                                "MemberHistory",
                            )
                            history_list = []
                    except (ValueError, TypeError) as e:
                        frappe.log_error(
                            f"Failed to parse fee_change_history for member {doc.name}: {e}", "MemberHistory"
                        )
                        history_list = []
                history_list.append(history_entry)

                # Update history directly in database
                frappe.db.sql(
                    """
                    UPDATE `tabMember`
                    SET fee_change_history = %s
                    WHERE name = %s
                """,
                    (frappe.as_json(history_list), doc.name),
                )

                # Update dues schedules if needed
                try:
                    # Create a temporary member object to avoid modifying the original
                    temp_member = frappe.get_doc("Member", doc.name)
                    # Mark as system update to bypass fee override validation
                    temp_member._system_update = True
                    result = temp_member.update_active_dues_schedules()
                    frappe.logger().info(f"Dues schedule update result: {result}")
                except Exception as e:
                    frappe.logger().error(f"Error updating dues schedules: {str(e)}")

                # Commit the transaction
                frappe.db.commit()

            except Exception as transaction_error:
                # Rollback the transaction on error
                frappe.db.rollback()
                frappe.logger().error(
                    f"Transaction error processing fee override for member {doc.name}: {str(transaction_error)}"
                )
                raise transaction_error

            delattr(doc, "_pending_fee_change")
            frappe.logger().info(f"Successfully processed fee override change for member {doc.name}")

        except Exception as e:
            frappe.logger().error(f"Error processing fee override for member {doc.name}: {str(e)}")
            # Clean up the pending change to avoid repeated processing
            if hasattr(doc, "_pending_fee_change"):
                delattr(doc, "_pending_fee_change")
    else:
        frappe.logger().debug(f"No pending fee change found for member {doc.name}")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def get_linked_donations(member):
    """
    Find linked donor record for a member to view donations
    """
    if not member:
        return {"success": False, "message": "No member specified"}

    # First try to find a donor with the same email as the member
    member_doc = frappe.get_doc("Member", member)
    if member_doc.email:
        donors = frappe.get_all("Donor", filters={"donor_email": member_doc.email}, fields=["name"])

        if donors:
            return {"success": True, "donor": donors[0].name}

    # Then try to find by name
    if member_doc.full_name:
        donors = frappe.get_all(
            "Donor", filters={"donor_name": ["like", f"%{member_doc.full_name}%"]}, fields=["name"]
        )

        if donors:
            return {"success": True, "donor": donors[0].name}

    # No donor found
    return {"success": False, "message": "No donor record found for this member"}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def assign_member_id(member_name):
    """Assign member ID - delegates to MemberIDService"""
    from verenigingen.services.member.identification.member_id_service import MemberIDService

    return MemberIDService.assign_member_id(member_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def validate_mandate_creation(member, iban, mandate_id):
    """
    Validate mandate creation parameters and check for existing mandates

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.validate_mandate_creation` instead.
        This function will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "validate_mandate_creation() is deprecated. Use SEPAMandateManager.validate_mandate_creation() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    frappe.log_error(
        "Deprecated function validate_mandate_creation() called. Migrate to SEPAMandateManager.",
        "Deprecation Warning",
    )
    try:
        # Check if member exists
        if not frappe.db.exists("Member", member):
            return {"error": _("Member does not exist")}

        # Check if mandate ID already exists
        existing_mandate = frappe.db.exists("SEPA Mandate", {"mandate_id": mandate_id})
        if existing_mandate:
            return {"error": _("Mandate ID {0} already exists").format(mandate_id)}

        # Check for existing active mandates for this member
        existing_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member, "status": "Active", "is_active": 1},
            fields=["name", "mandate_id", "iban"],
        )

        # Check if there's an existing mandate for the same IBAN
        iban_mandate = None
        for mandate in existing_mandates:
            if mandate.iban == iban:
                iban_mandate = mandate.mandate_id
                break

        result = {"valid": True}

        if iban_mandate:
            result["existing_mandate"] = iban_mandate
            result["warning"] = _("An active mandate already exists for this IBAN: {0}").format(iban_mandate)

        return result

    except Exception as e:
        frappe.log_error(f"Error validating mandate creation: {str(e)}")
        return {"error": _("Error validating mandate: {0}").format(str(e))}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def derive_bic_from_iban(iban):
    """
    Derive BIC code from IBAN

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.validation_service.PaymentValidationService.validate_bank_details` with auto_derive_bic=True instead.
        This function will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "derive_bic_from_iban() is deprecated. Use PaymentValidationService.validate_bank_details() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    frappe.log_error(
        "Deprecated function derive_bic_from_iban() called. Migrate to PaymentValidationService.",
        "Deprecation Warning",
    )
    try:
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch.direct_debit_batch import (
            get_bic_from_iban,
        )

        bic = get_bic_from_iban(iban)
        return {"bic": bic} if bic else {"bic": None}
    except Exception as e:
        frappe.log_error(f"Error deriving BIC from IBAN {iban}: {str(e)}")
        return {"bic": None}


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def deactivate_old_sepa_mandates(member, new_iban):
    """
    Deactivate old SEPA mandates when IBAN changes

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.deactivate_mandates_for_iban_change` instead.
        This function will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "deactivate_old_sepa_mandates() is deprecated. Use SEPAMandateManager.deactivate_mandates_for_iban_change() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    frappe.log_error(
        "Deprecated function deactivate_old_sepa_mandates() called. Migrate to SEPAMandateManager.",
        "Deprecation Warning",
    )
    try:
        # Get all active mandates for this member
        active_mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": member, "status": "Active", "is_active": 1},
            fields=["name", "iban", "mandate_id", "status"],
        )

        # ✅ SERVICE LAYER EXTRACTION: Use repository for SEPA mandate operations
        # Replaces 75 lines of complex batch update logic with clean repository call
        from verenigingen.repositories import SEPAMandateRepository

        sepa_repo = SEPAMandateRepository()

        # Get actual old IBAN from first active mandate (more reliable than parameter)
        old_iban = active_mandates[0].iban if active_mandates else new_iban

        # Batch deactivation with detailed reason including IBAN change
        results = sepa_repo.deactivate_mandates_for_member_iban_change(
            member_name=member, old_iban=old_iban, new_iban=new_iban
        )

        # Aggregate results
        successful = [name for name, r in results.items() if r.success]
        failed = [name for name, r in results.items() if not r.success]

        deactivated_count = len(successful)
        deactivated_mandates = []

        # Build response data for successful deactivations
        for mandate in active_mandates:
            if mandate.name in successful:
                deactivated_mandates.append({"mandate_id": mandate.mandate_id, "old_iban": mandate.iban})

        # Log failures
        if failed:
            frappe.log_error(
                f"Failed to deactivate {len(failed)} SEPA mandates: {', '.join(failed)}",
                "SEPA Mandate Batch Deactivation Failure",
            )

        return {
            "success": True,
            "deactivated_count": deactivated_count,
            "deactivated_mandates": deactivated_mandates,
        }

    except Exception as e:
        frappe.log_error(f"Error deactivating old SEPA mandates for member {member}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def refresh_sepa_mandates(member):
    """Refresh the SEPA mandates child table by syncing with actual SEPA Mandate records"""
    try:
        member_doc = frappe.get_doc("Member", member)
        result = member_doc.refresh_sepa_mandates_table()
        return result

    except Exception as e:
        frappe.log_error(f"Error refreshing SEPA mandates for member {member}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_active_sepa_mandate(member, iban=None):
    """
    Get active SEPA mandate for a member

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.get_active_mandates` instead.
        This function will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "get_active_sepa_mandate() is deprecated. Use SEPAMandateManager.get_active_mandates() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    frappe.log_error(
        "Deprecated function get_active_sepa_mandate() called. Migrate to SEPAMandateManager.",
        "Deprecation Warning",
    )
    try:
        filters = {"member": member, "status": "Active", "is_active": 1}

        if iban:
            filters["iban"] = iban

        mandates = frappe.get_all(
            "SEPA Mandate",
            filters=filters,
            fields=["name", "mandate_id", "status", "iban", "account_holder_name"],
            order_by="creation desc",
            limit=1,
        )

        return mandates[0] if mandates else None

    except Exception as e:
        frappe.log_error(f"Error getting active SEPA mandate for member {member}: {str(e)}")
        return None


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def assign_missing_member_ids():
    """Assign missing member IDs - delegates to MemberIDService"""
    from verenigingen.services.member.identification.member_id_service import MemberIDService

    return MemberIDService.assign_missing_member_ids()


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_and_link_mandate_enhanced(
    member,
    mandate_id,
    iban,
    bic="",
    account_holder_name="",
    mandate_type="Recurring",
    sign_date=None,
    used_for_memberships=1,
    used_for_donations=0,
    notes="",
    replace_existing=None,
):
    """
    Create a new SEPA mandate and link it to the member

    .. deprecated:: 2025-10-14
        Use :func:`verenigingen.services.payment.sepa_mandate_manager.SEPAMandateManager.create_mandate` instead.
        This function will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "create_and_link_mandate_enhanced() is deprecated. Use SEPAMandateManager.create_mandate() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    frappe.log_error(
        "Deprecated function create_and_link_mandate_enhanced() called. Migrate to SEPAMandateManager.",
        "Deprecation Warning",
    )
    try:
        # Validate mandatory fields before proceeding
        if not member or not member.strip():
            return {"success": False, "error": "Member is required"}

        if not mandate_id or not mandate_id.strip():
            return {"success": False, "error": "Mandate ID is required"}

        if not iban or not iban.strip():
            return {"success": False, "error": "IBAN is required for SEPA mandate creation"}

        if not account_holder_name or not account_holder_name.strip():
            return {"success": False, "error": "Account holder name is required"}

        # Validate member exists
        if not frappe.db.exists("Member", member):
            return {"success": False, "error": f"Member {member} does not exist"}

        # Validate IBAN format
        from verenigingen.utils.validation.iban_validator import validate_iban

        iban_validation = validate_iban(iban)
        if not iban_validation.get("valid"):
            return {
                "success": False,
                "error": f"Invalid IBAN: {iban_validation.get('error', 'Unknown IBAN validation error')}",
            }

        if not sign_date:
            sign_date = today()

        # Convert mandate type to internal format
        type_mapping = {"One-off": "OOFF", "One-of": "OOFF", "Recurring": "RCUR"}
        internal_type = type_mapping.get(mandate_type, "RCUR")

        # Create mandate
        mandate = frappe.new_doc("SEPA Mandate")
        mandate.mandate_id = mandate_id
        mandate.member = member
        mandate.iban = iban
        mandate.bic = bic
        mandate.account_holder_name = account_holder_name
        mandate.mandate_type = internal_type
        mandate.sign_date = sign_date
        from verenigingen.utils.boolean_utils import cbool

        mandate.used_for_memberships = cbool(used_for_memberships)
        mandate.used_for_donations = cbool(used_for_donations)
        mandate.status = "Active"
        mandate.is_active = 1
        mandate.notes = notes

        mandate.insert()

        # Update member's SEPA mandates table
        member_doc = frappe.get_doc("Member", member)

        # Mark existing mandates as non-current if replacing
        if replace_existing:
            for link in member_doc.sepa_mandates:
                if link.mandate_reference == replace_existing:
                    link.is_current = 0

        # Check if this mandate is already linked to avoid duplicates
        existing_link = None
        for link in member_doc.sepa_mandates:
            if link.mandate_reference == mandate_id:
                existing_link = link
                break

        if existing_link:
            # Update existing link
            existing_link.sepa_mandate = mandate.name
            existing_link.is_current = 1
            existing_link.status = "Active"
            existing_link.valid_from = sign_date
        else:
            # Add new mandate link
            member_doc.append(
                "sepa_mandates",
                {
                    "sepa_mandate": mandate.name,
                    "mandate_reference": mandate_id,
                    "is_current": 1,
                    "status": "Active",
                    "valid_from": sign_date,
                },
            )

        member_doc.save()

        return {"success": True, "mandate_name": mandate.name, "mandate_id": mandate_id}

    except frappe.ValidationError as e:
        # Handle validation errors gracefully
        error_msg = str(e)
        if "iban" in error_msg.lower():
            return {"success": False, "error": "Invalid IBAN format. Please provide a valid IBAN."}
        elif "mandate_id" in error_msg.lower():
            return {"success": False, "error": "Invalid mandate ID. Please provide a unique mandate ID."}
        elif "account_holder_name" in error_msg.lower():
            return {"success": False, "error": "Account holder name is required."}
        else:
            return {"success": False, "error": f"Validation error: {error_msg}"}

    except frappe.DuplicateEntryError:
        return {
            "success": False,
            "error": "A mandate with this ID already exists. Please use a different mandate ID.",
        }

    except Exception as e:
        # Log unexpected errors for debugging
        frappe.log_error(f"Unexpected error creating SEPA mandate: {str(e)}", "SEPA Mandate Creation Error")
        return {
            "success": False,
            "error": "An unexpected error occurred while creating the SEPA mandate. Please try again or contact support.",
        }


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_member_id_assignment(member_name):
    """Debug member ID assignment - delegates to MemberIDService"""
    from verenigingen.services.member.identification.member_id_service import MemberIDService

    return MemberIDService.debug_member_id_assignment(member_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_member_user_account(member_name, send_welcome_email=True):
    """
    Create a user account for a member to access portal pages.

    EXTRACTED: Moved to MemberUserAccountService.create_member_user_account()
    for service layer separation.

    Args:
        member_name: Name/ID of the member document
        send_welcome_email: Whether to send welcome email (default True)

    Returns:
        dict: Result dictionary with success, message, user, and action
    """
    from verenigingen.services.member.account.member_user_account_service import MemberUserAccountService

    return MemberUserAccountService.create_member_user_account(member_name, send_welcome_email)


# NOTE: Member role management functions have been extracted to MemberRoleService
# - add_member_roles_to_user() → MemberRoleService.add_member_roles_to_user()
# - set_member_user_modules() → MemberRoleService.set_member_user_modules()
# - _assign_individual_member_roles() → MemberRoleService._assign_individual_member_roles()
# - create_verenigingen_member_role() → MemberRoleService.create_verenigingen_member_role()


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def check_donor_exists(member_name):
    """Check if a donor record exists for this member"""
    from verenigingen.services.member.donor import DonorManagementService

    return DonorManagementService.check_donor_exists(member_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_donor_from_member(member_name):
    """
    Create a donor record from member information.

    EXTRACTED: Moved to MemberDonorIntegrationService.create_donor_from_member()
    for service layer separation.

    Args:
        member_name: Name/ID of the member document

    Returns:
        dict: Result dictionary with success, message, and donor_name
    """
    from verenigingen.services.member.integration.member_donor_integration_service import (
        MemberDonorIntegrationService,
    )

    return MemberDonorIntegrationService.create_donor_from_member(member_name)

    def _load_volunteer_assignment_history(self):
        """Load volunteer assignment history from linked volunteer record"""
        try:
            # Clear existing volunteer assignment history
            self.volunteer_assignment_history = []

            # Get linked volunteer record
            volunteer = get_volunteer_for_member(self.name)
            if not volunteer:
                return

            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            # Copy assignment history from volunteer to member
            for assignment in volunteer_doc.assignment_history or []:
                self.append(
                    "volunteer_assignment_history",
                    {
                        "assignment_type": assignment.assignment_type,
                        "reference_doctype": assignment.reference_doctype,
                        "reference_name": assignment.reference_name,
                        "role": assignment.role,
                        "start_date": assignment.start_date,
                        "end_date": assignment.end_date,
                        "status": assignment.status,
                        "title": assignment.get("title", ""),
                    },
                )

        except Exception as e:
            frappe.log_error(f"Error loading volunteer assignment history for member {self.name}: {str(e)}")

    @frappe.whitelist()
    @development_only_api(operation_type=OperationType.UTILITY)
    def debug_address_members(self):
        """Debug method to test address members functionality"""
        try:
            result = {
                "member_id": self.name,
                "member_name": f"{self.first_name} {self.last_name}",
                "primary_address": self.primary_address,
                "address_members_html": None,
                "address_members_html_length": 0,
                "other_members_count": 0,
                "other_members_list": [],
            }

            # Test the HTML generation
            html_result = self.get_address_members_html()
            result["address_members_html"] = html_result
            result["address_members_html_length"] = len(html_result) if html_result else 0

            # Test the underlying method
            other_members = self.get_other_members_at_address()
            result["other_members_count"] = len(other_members) if other_members else 0
            result["other_members_list"] = other_members if other_members else []

            return result

        except Exception as e:
            return {"error": str(e), "traceback": frappe.get_traceback()}

    def _get_linked_donations(self):
        """Get donations linked to this member"""
        try:
            return frappe.get_all(
                "Donation",
                filters={"donor": self.name},
                fields=["name", "amount", "donation_date", "status"],
                order_by="donation_date desc",
            )
        except Exception:
            return []


# Global functions that were missing from current version


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_current_chapters(member_name):
    """
    Get current chapters for a member - safe for client calls.

    Delegates to ChapterManagementService for optimized query execution.
    This function maintains backward compatibility for API endpoints.
    """
    if not member_name:
        return []

    try:
        from verenigingen.services.member.chapter.chapter_management_service import ChapterManagementService

        # Use optimized service method
        return ChapterManagementService.get_member_chapters_optimized(member_name)

    except frappe.PermissionError:
        # If no permission to member, return empty list (API compatibility)
        return []
    except Exception as e:
        frappe.log_error(f"Error getting member chapters: {str(e)}", "Member Chapters API")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_chapter_names(member_name):
    """
    Get simple list of chapter names for a member.

    Delegates to ChapterManagementService for optimized query execution.
    """
    if not member_name:
        return []

    try:
        from verenigingen.services.member.chapter.chapter_management_service import ChapterManagementService

        return ChapterManagementService.get_chapter_names(member_name)
    except Exception as e:
        frappe.log_error(f"Error getting member chapter names: {str(e)}", "Member Chapter Names API")
        return []


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_chapter_display_html(member_name):
    """
    Get HTML display of member's chapters.

    Delegates to ChapterManagementService for optimized query execution.
    """
    if not member_name:
        return "<div class='text-muted'>No member specified</div>"

    try:
        from verenigingen.services.member.chapter.chapter_management_service import ChapterManagementService

        return ChapterManagementService.get_chapter_display_html(member_name)

    except Exception as e:
        frappe.log_error(f"Error generating chapter display HTML: {str(e)}", "Member Chapter Display")
        return f"<div class='text-danger'>Error loading chapters: {str(e)}</div>"


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def sync_member_dues_rate(member_name):
    """Sync member's dues_rate field with their active dues schedule"""
    try:
        # Get the member's active dues schedule
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            ["name", "dues_rate"],
            as_dict=True,
        )

        if schedule:
            # Update member's dues_rate field
            member_doc = frappe.get_doc("Member", member_name)
            member_doc.dues_rate = schedule.dues_rate
            member_doc.save()
            return {
                "success": True,
                "message": f"Synced dues rate: {schedule.dues_rate}",
                "dues_rate": schedule.dues_rate,
            }
        else:
            return {"success": False, "message": "No active dues schedule found"}
    except Exception as e:
        frappe.log_error(f"Error syncing member dues rate: {str(e)}", "Member Dues Rate Sync")
        return {"success": False, "message": f"Error: {str(e)}"}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_current_dues_schedule_details(member):
    """Get current dues schedule details for a member"""
    try:
        # Get active dues schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member, "status": "Active"},
            ["name", "dues_rate", "billing_frequency", "next_invoice_date", "membership_type"],
            as_dict=True,
        )

        if not dues_schedule:
            return {"has_schedule": False, "message": "No active dues schedule found"}

        # Get membership type details
        membership_type = None
        if dues_schedule.membership_type:
            membership_type = frappe.db.get_value(
                "Membership Type",
                dues_schedule.membership_type,
                ["membership_type_name", "description"],
                as_dict=True,
            )

        return {
            "has_schedule": True,
            "schedule_name": dues_schedule.name,
            "dues_rate": dues_schedule.dues_rate,
            "billing_frequency": dues_schedule.billing_frequency,
            "next_invoice_date": dues_schedule.next_invoice_date,
            "membership_type": dues_schedule.membership_type,
            "membership_type_name": membership_type.membership_type_name if membership_type else None,
            "membership_type_description": membership_type.description if membership_type else None,
        }

    except Exception as e:
        frappe.log_error(
            f"Error getting dues schedule details for member {member}: {str(e)}", "Dues Schedule Details"
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def refresh_fee_change_history(member_name):
    """
    Refresh fee change history from dues schedules with integrity checking.

    EXTRACTED: Moved to MemberHistoryUpdateService.refresh_fee_change_history()
    for service layer separation.

    Args:
        member_name: Name/ID of the member document

    Returns:
        dict: Result dictionary with success, message, and statistics
    """
    from verenigingen.services.member.history.member_history_update_service import MemberHistoryUpdateService

    return MemberHistoryUpdateService.refresh_fee_change_history(member_name)


# =============================================================================
# DELEGATION FUNCTIONS FOR EXTRACTED UTILITIES
# =============================================================================
# The following functions delegate to extracted testing and debugging utilities
# to maintain API compatibility while keeping member.py focused on core business logic.


@frappe.whitelist()
def test_member_form_functionality(member_name):
    """Delegate to extracted testing utility."""
    from verenigingen.services.member.testing.member_test_utilities import test_member_form_functionality

    return test_member_form_functionality(member_name)
