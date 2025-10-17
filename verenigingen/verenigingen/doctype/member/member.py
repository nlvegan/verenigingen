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
        """Check if chapter display needs updating to avoid unnecessary processing.

        Implements smart change detection to avoid expensive geographic lookups
        and database queries when chapter assignment hasn't changed.

        Returns:
            bool: True if chapter display should be updated

        Triggers:
            - Existing records being updated (skip for brand new unsaved records)
            - Address field changes (pincode, city, state)
            - Explicit chapter assignment operations
        """
        # Skip for new records that don't exist in DB yet - they won't have chapters
        # Chapters are assigned after the member is created and saved
        if self.is_new():
            return False

        # Check if geographic fields have changed that affect chapter assignment
        chapter_related_fields = ["pincode", "city", "state"]
        for field in chapter_related_fields:
            if hasattr(self, "has_value_changed") and self.has_value_changed(field):
                return True

        # Allow explicit updates during chapter assignment workflows
        if hasattr(self, "_chapter_assignment_in_progress"):
            return True

        return False

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
        """Validate fee override amount is positive"""
        if amount and amount <= 0:
            frappe.throw(_("Membership fee override must be greater than 0"))

    def _validate_fee_override_reason(self):
        """Centralized fee override reason validation logic"""
        if not self.dues_rate:
            return

        is_csv_import = getattr(self, "_csv_import", False)
        is_system_update = getattr(self, "_system_update", False)
        is_in_test = getattr(frappe.flags, "in_test", False)
        fee_override_reason = getattr(self, "fee_override_reason", None)

        frappe.logger("member_validation").info(
            f"Fee override validation: member={self.name or 'NEW'}, dues_rate={self.dues_rate}, "
            f"is_csv_import={is_csv_import}, is_system_update={is_system_update}, "
            f"is_in_test={is_in_test}, fee_override_reason={fee_override_reason}"
        )

        if not (is_csv_import or is_system_update or is_in_test) and not fee_override_reason:
            frappe.throw(_("Please provide a reason for the fee override"))

    def validate_fee_override_permissions(self):
        """Validate that only authorized users can set fee overrides"""
        # Skip validation for new documents or if no override is set
        if self.is_new() or not self.dues_rate:
            return

        # Skip validation if this is a system update (e.g., from amendment request)
        if getattr(self, "_system_update", False):
            return

        # Check if fee override value has changed
        if self.name:
            old_amount = frappe.db.get_value("Member", self.name, "dues_rate")
            if old_amount == self.dues_rate:
                return  # No change, no validation needed

        # Check user permissions for fee override
        user_roles = frappe.get_roles(frappe.session.user)
        authorized_roles = ["System Manager", "Verenigingen Staff", "Verenigingen Administrator"]

        if not any(role in user_roles for role in authorized_roles):
            frappe.throw(
                _(
                    "You do not have permission to override membership fees. Only administrators can modify membership fees."
                ),
                frappe.PermissionError,
            )

        # Log the fee override action for audit purposes
        frappe.logger().info(
            f"Fee override set by {frappe.session.user} for member {self.name}: "
            f"Amount: {self.dues_rate}, Reason: {getattr(self, 'fee_override_reason', 'No reason provided')}"
        )

    def before_insert(self):
        """Execute before inserting new document"""
        # Member ID generation is now handled in before_save based on application status

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def get_address_members_html(self):
        """Get HTML content for address members field - called from JavaScript"""
        try:
            if not self.primary_address:
                return '<div class="text-muted"><i class="fa fa-home"></i> No address selected</div>'

            # Get other members at the same address
            other_members = self.get_other_members_at_address()

            if other_members:
                # Create HTML content for display
                html_content = f'<div class="address-members-display"><h6>Other Members at This Address ({len(other_members)} found): </h6>'

                for other in other_members:
                    html_content += f"""
                    <div class="member-card" style="border: 1px solid #ddd; padding: 8px; margin: 4px 0; border-radius: 4px; background: #f8f9fa;">
                        <strong>{other.get("full_name", "Unknown")}</strong>
                        <span class="text-muted">({other.get("name", "Unknown ID")})</span>
                        <br><small class="text-muted">
                            <i class="fa fa-users"></i> {other.get("relationship", "Unknown")} |
                            <i class="fa fa-birthday-cake"></i> {other.get("age_group", "Unknown")} |
                            <i class="fa fa-circle text-{self._get_status_color(other.get("status", "Unknown"))}"></i> {other.get("status", "Unknown")}
                        </small>
                        <br><small class="text-muted">
                            <i class="fa fa-envelope"></i> {other.get("email", "Unknown")}
                        </small>
                    </div>
                    """
                html_content += "</div>"
                return html_content
            else:
                # No other members found
                return '<div class="text-muted"><i class="fa fa-info-circle"></i> No other members found at this address</div>'

        except Exception as e:
            frappe.log_error(f"Error loading address members for {self.name}: {str(e)}")
            return f'<div class="text-danger"><i class="fa fa-exclamation-triangle"></i> Error loading member information: {str(e)}</div>'

    def _get_status_color(self, status):
        """Get Bootstrap color class for member status - delegated to member_status_service"""
        from verenigingen.services.member.core.member_status_service import get_member_status_color

        return get_member_status_color(status)

    @frappe.whitelist()
    @development_only_api(operation_type=OperationType.UTILITY)
    def test_member_form_functionality(self):
        """Test Member form loading and functionality"""
        results = {"status": "success", "member_name": self.name, "tests": [], "errors": []}

        try:
            # Test 1: Onload method
            try:
                self.onload()
                results["tests"].append(
                    {"test": "onload() method", "status": "passed", "message": "Executed without errors"}
                )
            except Exception as e:
                results["tests"].append(
                    {"test": "onload() method", "status": "failed", "message": f"Error: {str(e)}"}
                )
                results["errors"].append(f"Onload error: {str(e)}")

            # Test 2: Address optimization functionality
            try:
                if hasattr(self, "get_other_members_at_address"):
                    other_members = self.get_other_members_at_address()
                    count = len(other_members) if other_members else 0
                    results["tests"].append(
                        {
                            "test": "Address optimization",
                            "status": "passed",
                            "message": f"Found {count} other members",
                        }
                    )
                else:
                    results["tests"].append(
                        {"test": "Address optimization", "status": "failed", "message": "Method not found"}
                    )
            except Exception as e:
                results["tests"].append(
                    {"test": "Address optimization", "status": "failed", "message": f"Error: {str(e)}"}
                )
                results["errors"].append(f"Address optimization error: {str(e)}")

            # Test 3: HTML field updates
            try:
                if hasattr(self, "update_other_members_at_address_display"):
                    self.update_other_members_at_address_display()
                    results["tests"].append(
                        {
                            "test": "Address display update",
                            "status": "passed",
                            "message": "Completed successfully",
                        }
                    )
                else:
                    results["tests"].append(
                        {"test": "Address display update", "status": "failed", "message": "Method not found"}
                    )
            except Exception as e:
                results["tests"].append(
                    {"test": "Address display update", "status": "failed", "message": f"Error: {str(e)}"}
                )
                results["errors"].append(f"Display update error: {str(e)}")

            # Test 4: Check field content
            try:
                field_content = getattr(self, "other_members_at_address", None)
                if field_content:
                    results["tests"].append(
                        {"test": "Address links display", "status": "passed", "message": "Field has content"}
                    )
                else:
                    results["tests"].append(
                        {"test": "Address links display", "status": "warning", "message": "Field is empty"}
                    )
            except Exception as e:
                results["tests"].append(
                    {"test": "Address links display", "status": "failed", "message": f"Error: {str(e)}"}
                )

        except Exception as e:
            results["status"] = "error"
            results["errors"].append(f"Critical error: {str(e)}")

        return results

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
        """Create user account for member if conditions are met"""
        try:
            # Don't create user for application members (handled in approval process)
            if self.is_application_member():
                return

            # Don't create if user already exists
            if self.user:
                return

            # Must have email to create user
            if not self.email:
                return

            # Only create for active members
            if getattr(self, "status", "") not in ["Active", ""]:
                return

            # Create user account
            result = create_member_user_account(self.name, send_welcome_email=False)

            if result.get("success"):
                frappe.logger().info(f"Auto-created user account for manually created member {self.name}")
            else:
                frappe.logger().warning(
                    f"Could not auto-create user account for member {self.name}: {result.get('error', 'Unknown error')}"
                )

        except Exception as e:
            frappe.log_error(f"Error in create_user_account_if_needed for member {self.name}: {str(e)}")
            # Don't raise exception to avoid blocking member save

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
                    self.update_other_members_at_address_display()
                    # Ensure the HTML field is included in the response
                    if hasattr(self, "other_members_at_address") and self.other_members_at_address:
                        self.set_onload("other_members_at_address", self.other_members_at_address)
                except Exception as e:
                    frappe.log_error(
                        f"Error updating other members at address display in onload for {self.name}: {e}"
                    )

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
        """Attempt to guess relationship based on name patterns and data"""
        # Handle both dict and object inputs
        other_full_name = (
            other_member.get("full_name")
            if isinstance(other_member, dict)
            else getattr(other_member, "full_name", None)
        )
        other_birth_date = (
            other_member.get("birth_date")
            if isinstance(other_member, dict)
            else getattr(other_member, "birth_date", None)
        )

        if not other_full_name or not self.full_name:
            return "Household Member"

        # Check if they share a last name
        self_parts = self.full_name.strip().split()
        other_parts = other_full_name.strip().split()

        if len(self_parts) > 0 and len(other_parts) > 0:
            self_last = self_parts[-1].lower()
            other_last = other_parts[-1].lower()

            if self_last == other_last:
                # Same last name - likely family
                if self.birth_date and other_birth_date:
                    try:
                        self_date = getdate(self.birth_date)
                        other_date = getdate(other_birth_date)
                        age_diff = abs((self_date - other_date).days // 365)

                        if age_diff < 5:
                            return "Spouse/Partner"
                        elif age_diff > 15:
                            return "Parent/Child"
                        else:
                            return "Sibling"
                    except Exception:
                        pass
                return "Family Member"
            else:
                return "Partner/Spouse"

        return "Household Member"

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
        """Create membership record when application is approved

        Args:
            start_date: Custom start date for membership (defaults to today)
            create_invoice: Whether to create invoice (False for historic CSV imports)
            custom_dues_rate: Custom dues rate for CSV imports (bypasses normal calculation)
            custom_rate_reason: Reason for custom dues rate
            is_csv_import: Flag indicating this is from CSV import with historic date
            approval_fields: Dict of approval fields to set (application_status, reviewed_by, etc.)
        """
        frappe.logger().info(
            f"[MEMBER DEBUG] create_membership_on_approval called for {self.name}, "
            f"bulk_member_operations={getattr(frappe.flags, 'bulk_member_operations', 'NOT SET')}, "
            f"start_date={start_date}, create_invoice={create_invoice}, custom_dues_rate={custom_dues_rate}"
        )
        try:
            # Get membership type
            if not self.selected_membership_type:
                frappe.throw(_("No membership type selected for this application"))

            membership_type = frappe.get_doc("Membership Type", self.selected_membership_type)

            # Set custom dues rate on member if provided (for CSV imports)
            if custom_dues_rate:
                # Save to database immediately so membership.on_submit() can read it
                frappe.db.set_value(
                    "Member",
                    self.name,
                    {
                        "csv_import_custom_fee": custom_dues_rate,
                        "csv_import_custom_fee_reason": custom_rate_reason or "Imported from CSV",
                    },
                    update_modified=False,
                )

            # Check for existing active membership from previous failed approval attempt
            existing_membership = frappe.db.get_value(
                "Membership",
                {"member": self.name, "status": "Active", "docstatus": 1},
                ["name", "membership_type", "start_date"],
                as_dict=True,
            )

            if existing_membership:
                # Reuse existing membership if it matches selected type and has recent start date
                # This handles retry scenarios where membership was created but approval failed
                days_old = date_diff(today(), existing_membership.start_date)
                same_type = existing_membership.membership_type == self.selected_membership_type

                if same_type and days_old <= 1:
                    # Existing membership is appropriate - reuse it
                    frappe.logger().info(
                        f"Reusing existing membership {existing_membership.name} for member {self.name} (retry scenario)"
                    )
                    membership = frappe.get_doc("Membership", existing_membership.name)
                else:
                    # Existing membership is wrong type or too old - fail with clear message
                    frappe.throw(
                        _(
                            "Member already has an active membership ({0}) with type '{1}' from {2}. "
                            "Please cancel the existing membership before approving with a different type."
                        ).format(
                            existing_membership.name,
                            existing_membership.membership_type,
                            frappe.format_date(existing_membership.start_date),
                        )
                    )
            else:
                # No existing membership - create new one
                membership = frappe.get_doc(
                    {
                        "doctype": "Membership",
                        "member": self.name,
                        "membership_type": self.selected_membership_type,
                        "start_date": start_date or today(),
                        "status": "Active",  # Active immediately on approval
                    }
                )

                # Set CSV import flag for proper renewal_date calculation
                if is_csv_import:
                    membership._is_csv_import = True

                # Use context manager to skip member updates in membership.on_submit()
                # We'll consolidate all updates into one save below for performance
                from verenigingen.utils.document_coordination import skip_child_document_updates

                with skip_child_document_updates(
                    self, "Membership", "Consolidating member updates for approval performance"
                ):
                    membership.insert()
                    membership.submit()  # Submit to make it fully active

            # Set this as the member's current membership plan
            self.current_membership_plan = membership.name

            # Ensure dues schedule exists (handles both new and reused memberships)
            # This was previously done in membership.on_submit() hook, but that doesn't run for reused memberships
            existing_schedule = frappe.db.get_value(
                "Membership Dues Schedule", {"member": self.name, "is_template": 0}, "name"
            )

            if not existing_schedule:
                # Create dues schedule explicitly instead of relying on hook
                from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                    MembershipDuesSchedule,
                )

                try:
                    schedule_name = MembershipDuesSchedule.create_from_template(
                        self.name, membership_type=membership.membership_type, membership_name=membership.name
                    )
                    frappe.logger().info(
                        f"Created dues schedule {schedule_name} for member {self.name} during approval"
                    )
                except Exception as e:
                    frappe.logger().error(f"Failed to create dues schedule for member {self.name}: {str(e)}")
                    # Don't fail approval if dues schedule creation fails - it can be created later
                    frappe.msgprint(
                        _("Warning: Dues schedule creation failed. It will be retried automatically."),
                        alert=True,
                        indicator="orange",
                    )

            # Generate invoice with member's custom fee if applicable (skip for CSV imports)
            invoice = None
            if create_invoice:
                from verenigingen.utils.application_payments import create_membership_invoice

                current_fee = self.get_current_membership_fee()
                invoice = create_membership_invoice(self, membership, membership_type, current_fee["amount"])

            # Reload member to get latest data and update all fields in one save
            frappe.logger().info(f"[MEMBER DEBUG] Reloading member {self.name} to consolidate all updates")
            self.reload()

            # Set current membership plan (was set before but reload wiped it)
            self.current_membership_plan = membership.name

            # Set current dues schedule (normally done by membership.update_member_current_membership_plan)
            dues_schedule = frappe.db.get_value(
                "Membership Dues Schedule", {"member": self.name, "is_template": 0}, "name"
            )
            if dues_schedule:
                self.current_dues_schedule = dues_schedule

            # Update membership duration (normally done by membership.update_member_duration)
            from verenigingen.services.member.utils.membership_duration_service import (
                update_member_duration_fields,
            )

            update_member_duration_fields(self)  # Updates fields in-place, doesn't save

            # Set invoice fields if invoice was created
            if invoice:
                self.application_invoice = invoice.name
                self.application_payment_status = "Pending"

            # Set approval fields if provided (from approval workflow)
            if approval_fields:
                for field, value in approval_fields.items():
                    setattr(self, field, value)

            # Mark as system update to bypass fee override validation
            self._system_update = True

            # SECURITY AUDIT: Log validation bypass for compliance
            if self.dues_rate:
                frappe.logger().warning(
                    f"SECURITY_AUDIT: Fee override validation bypassed via _system_update "
                    f"for member {self.name}, dues_rate={self.dues_rate}, "
                    f"user={frappe.session.user}, context=create_membership_on_approval"
                )

            # Single consolidated save with retry logic and rollback on failure
            frappe.logger().info(f"[MEMBER DEBUG] Saving member {self.name} with all updates consolidated")

            # Define field restoration callback for retry logic
            def restore_member_fields(member_doc):
                """Restore all member fields after reload during retry"""
                member_doc.current_membership_plan = membership.name
                if dues_schedule:
                    member_doc.current_dues_schedule = dues_schedule
                # CRITICAL: Re-apply duration fields after reload
                update_member_duration_fields(member_doc)
                if invoice:
                    member_doc.application_invoice = invoice.name
                    member_doc.application_payment_status = "Pending"
                # Restore approval fields if provided
                if approval_fields:
                    for field, value in approval_fields.items():
                        setattr(member_doc, field, value)
                member_doc._system_update = True

                # SECURITY AUDIT: Log validation bypass for compliance
                if member_doc.dues_rate:
                    frappe.logger().warning(
                        f"SECURITY_AUDIT: Fee override validation bypassed via _system_update "
                        f"for member {member_doc.name}, dues_rate={member_doc.dues_rate}, "
                        f"user={frappe.session.user}, context=create_membership_on_approval"
                    )

            # Use retry utility with automatic rollback of membership if member save fails
            from verenigingen.utils.document_save_retry import save_with_rollback

            save_with_rollback(
                self,
                rollback_docs=[membership],  # Cancel membership if member save fails
                max_retries=1,
                field_restore_callback=restore_member_fields,
            )

            return membership

        except Exception as e:
            frappe.log_error(f"Error creating membership on approval: {str(e)}")
            frappe.throw(_("Error creating membership: {0}").format(str(e)))

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

        This prevents LinkExistsError by cleaning up all related documents
        that have Link fields pointing to this Member.

        Strategy:
        1. Delete critical child records (Memberships, Chapter Members)
        2. Handle Customer intelligently (preserve if has transactions)
        3. Unlink Addresses (preserve for historical reference)
        """
        # Delete related Membership records (both draft and submitted)
        memberships = frappe.get_all("Membership", filters={"member": self.name}, pluck="name")

        for membership_name in memberships:
            try:
                membership = frappe.get_doc("Membership", membership_name)
                # Cancel if submitted, then delete
                if membership.docstatus == 1:  # Submitted
                    membership.cancel()
                frappe.delete_doc("Membership", membership_name, force=True)
            except Exception as e:
                frappe.logger().error(f"Error deleting Membership {membership_name}: {str(e)}")

        # Delete Chapter Member assignments
        chapter_members = frappe.get_all("Chapter Member", filters={"member": self.name}, pluck="name")

        for chapter_member_name in chapter_members:
            try:
                frappe.delete_doc("Chapter Member", chapter_member_name, force=True)
            except Exception as e:
                frappe.logger().error(f"Error deleting Chapter Member {chapter_member_name}: {str(e)}")

        # Handle Customer - preserve if has transactions
        if self.customer:
            try:
                has_transactions = (
                    frappe.db.count("Sales Invoice", {"customer": self.customer}) > 0
                    or frappe.db.count("Payment Entry", {"party_type": "Customer", "party": self.customer})
                    > 0
                )

                if has_transactions:
                    # Unlink member from Customer's Dynamic Links
                    self._unlink_from_customer()
                    frappe.logger().info(
                        f"Customer {self.customer} has transactions - unlinked Member reference"
                    )
                else:
                    # No transactions - delete Customer
                    frappe.delete_doc("Customer", self.customer, force=True)
                    frappe.logger().info(f"Deleted Customer {self.customer}")

            except Exception as e:
                frappe.logger().error(f"Error handling Customer {self.customer}: {str(e)}")

        # Handle Addresses - unlink from Member but preserve records
        if self.primary_address:
            try:
                self._unlink_from_address(self.primary_address)
            except Exception as e:
                frappe.logger().error(f"Error unlinking Address {self.primary_address}: {str(e)}")

    def _unlink_from_customer(self):
        """Remove Member link from Customer's Dynamic Links table"""
        if not self.customer:
            return

        customer = frappe.get_doc("Customer", self.customer)
        # Remove any Dynamic Link entries pointing to this Member
        links_to_remove = [
            link
            for link in customer.get("links", [])
            if link.link_doctype == "Member" and link.link_name == self.name
        ]

        for link in links_to_remove:
            customer.remove(link)

        if links_to_remove:
            customer.save(ignore_permissions=True)

    def _unlink_from_address(self, address_name):
        """Remove Member link from Address's links table"""
        address = frappe.get_doc("Address", address_name)

        # Remove any link entries pointing to this Member
        links_to_remove = [
            link
            for link in address.get("links", [])
            if link.link_doctype == "Member" and link.link_name == self.name
        ]

        for link in links_to_remove:
            address.remove(link)

        if links_to_remove:
            address.save(ignore_permissions=True)

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
        """Create a user account for this member"""
        self.user = None
        if self.user:
            frappe.msgprint(_("User {0} already exists for this member").format(self.user))
            return self.user

        if not self.email:
            frappe.throw(_("Email is required to create a user"))

        if frappe.db.exists("User", self.email):
            user = frappe.get_doc("User", self.email)
            self.user = user.name
            self.save()
            frappe.msgprint(_("Linked to existing user {0}").format(user.name))
            return user.name

        user = frappe.new_doc("User")
        user.email = self.email
        user.first_name = self.first_name

        # Handle Dutch naming conventions for User creation
        if is_dutch_installation() and hasattr(self, "tussenvoegsel") and self.tussenvoegsel:
            # For Dutch installations, use combined last name with tussenvoegsel
            user.last_name = get_full_last_name(self.last_name, self.tussenvoegsel)
            # Don't use middle_name for User when we have tussenvoegsel
        else:
            # Standard naming for non-Dutch installations or when no tussenvoegsel
            user.last_name = self.last_name
            if self.middle_name:
                user.middle_name = self.middle_name

        user.send_welcome_email = 1
        user.user_type = "System User"

        # Secure user creation with explicit permission validation
        user_result = secure_document_operation(
            operation="insert",
            doc=user,
            justification=f"Automated user creation for member {self.name}",
            required_permissions=["User:create"],
        )

        if not user_result.success:
            frappe.throw(_("Failed to create user: {0}").format("; ".join(user_result.errors)))

        # Add member-specific roles after user is created
        add_member_roles_to_user(user.name)

        # Set allowed modules for member users
        set_member_user_modules(user.name)

        # Update user field directly to avoid timestamp conflicts
        frappe.db.set_value("Member", self.name, "user", user.name)
        self.user = user.name

        # Transfer ownership to the member's user account
        # This allows members to view and edit their own records
        if self.owner != user.name:
            frappe.db.set_value("Member", self.name, "owner", user.name)
            frappe.logger().info(
                f"Transferred ownership of member {self.name} from {self.owner} to {user.name}"
            )

        frappe.db.commit()

        frappe.msgprint(_("User {0} created successfully").format(user.name))
        return user.name

    def handle_fee_override_changes(self):
        """Handle changes to membership fee override using amendment system with better atomicity"""
        # Skip all fee override handling for CSV imports and bulk operations
        csv_flag = getattr(self, "_csv_import", False)
        system_flag = getattr(self, "_system_update", False)
        # Check if member is part of an active bulk import (persists across saves)
        in_bulk_import = (
            hasattr(frappe.local, "bulk_import_members") and self.name in frappe.local.bulk_import_members
        )

        if csv_flag or system_flag or in_bulk_import:
            return

        # Check permissions for fee override changes
        self.validate_fee_override_permissions()

        # Skip fee override change tracking for new member applications
        # Applications should set initial fee amounts without triggering change tracking
        if not self.name or self.is_new():
            # For new documents, validate and set audit fields but no change tracking
            if self.dues_rate:
                # Use centralized validation logic
                self._validate_fee_override_amount(self.dues_rate)
                self._validate_fee_override_reason()

                # For CSV imports, create audit log entry instead of requiring override fields
                if getattr(self, "_csv_import", False) and self.dues_rate:
                    frappe.logger().info(
                        f"CSV Import: Member {self.name or 'NEW'} imported with dues_rate {self.dues_rate}"
                    )

                # Set audit fields for new members (but no change tracking)
                if not getattr(self, "fee_override_date", None):
                    setattr(self, "fee_override_date", today())
                if not getattr(self, "fee_override_by", None):
                    setattr(self, "fee_override_by", frappe.session.user)
            return

        # Get current and old values for existing documents with better error handling
        new_amount = self.dues_rate
        old_amount = None

        try:
            # Get current value from database
            db_result = frappe.db.sql(
                """
                SELECT dues_rate
                FROM `tabMember`
                WHERE name = %s
            """,
                (self.name,),
                as_dict=True,
            )

            if db_result:
                old_amount = db_result[0].dues_rate

            # Check if values are actually different
            if old_amount == new_amount:
                return  # No change detected

            # If we reach here, there's an actual change to process
            frappe.logger().info(
                f"Processing fee override change for member {self.name}: {old_amount} -> {new_amount}"
            )

            # Set audit fields when adding or changing override
            if new_amount and not old_amount:
                self.fee_override_date = today()
                self.fee_override_by = frappe.session.user

            # Validate fee override
            if new_amount:
                # Use centralized validation logic
                self._validate_fee_override_amount(new_amount)
                self._validate_fee_override_reason()

            # Store change data for deferred processing to avoid save recursion
            self._pending_fee_change = {
                "old_amount": old_amount,
                "new_amount": new_amount,
                "reason": getattr(self, "fee_override_reason", None) or "No reason provided",
                "change_date": now(),
                "changed_by": frappe.session.user if frappe.session.user else "Administrator",
            }

            frappe.logger().info(f"Queued fee override change for member {self.name}")

        except Exception as e:
            frappe.logger().error(f"Error processing fee override change for member {self.name}: {str(e)}")
            # Don't fail the save operation, just log the error
            return

    def record_fee_change(self, change_data):
        """Record fee change in history using the financial history manager"""
        from verenigingen.utils.member_financial_history_manager import get_fee_change_history_manager

        # Use amendment request name for true idempotency, fallback to schedule+action for other changes
        amendment_name = change_data.get("amendment_request_name")
        if amendment_name:
            entry_id = f"amendment_{amendment_name}"
            id_field_name = "amendment_request"
        else:
            # For non-amendment changes: use schedule name + action type for deduplication
            # This prevents duplicate entries when same schedule action is processed multiple times
            schedule_name = change_data.get("dues_schedule_name", "unknown")
            action = change_data.get("dues_schedule_action", "manual")
            entry_id = f"{schedule_name}_{action}"
            id_field_name = "dues_schedule"

        def build_fee_change_entry():
            entry_data = {
                "change_date": change_data["change_date"],
                "old_dues_rate": change_data["old_amount"],
                "new_dues_rate": change_data["new_amount"],
                "change_type": change_data.get("change_type", "Fee Adjustment"),
                "reason": change_data["reason"],
                "changed_by": change_data["changed_by"],
                "dues_schedule": change_data.get("dues_schedule_name", ""),
                "dues_schedule_doctype": "Membership Dues Schedule",
            }
            # Add billing frequency if provided
            if "billing_frequency" in change_data:
                entry_data["billing_frequency"] = change_data["billing_frequency"]
            # Add amendment request reference if available
            if amendment_name:
                entry_data["amendment_request"] = amendment_name
                entry_data["amendment_request_doctype"] = "Contribution Amendment Request"
            return entry_data

        fee_history_manager = get_fee_change_history_manager(self)
        return fee_history_manager.add_or_update_entry(
            entry_id=entry_id,
            entry_builder=build_fee_change_entry,
            id_field_name=id_field_name,
        )

    def get_active_membership(self):
        """Get the currently active membership for this member.

        Delegates to the existing utility in member_utils for consistent
        membership lookup with field validation and error handling.

        Returns:
            Membership document if found, None otherwise
        """
        # Use the more sophisticated utility from member_utils
        membership_data = get_active_membership_for_member(
            self.name, fields=["name", "membership_type", "start_date", "renewal_date", "status"]
        )

        if membership_data:
            return frappe.get_doc("Membership", membership_data["name"])
        return None

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
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
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

        Extracted to membership_duration_service for reusability. Delegates to the
        extracted service for consistent duration formatting.

        Returns:
            float: Duration in years for backward compatibility
        """
        try:
            # Use the already calculated total_membership_days if available, otherwise calculate it
            total_days = getattr(self, "total_membership_days", 0) or self.calculate_total_membership_days()

            # Use extracted service for formatting
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
        """Get current effective membership fee for this member"""
        if self.dues_rate:
            return {
                "amount": self.dues_rate,
                "source": "custom_override",
                "reason": getattr(self, "fee_override_reason", None),
            }

        # Get from active membership
        active_membership = self.get_active_membership()
        if active_membership and active_membership.membership_type:
            membership_type = frappe.get_doc("Membership Type", active_membership.membership_type)
            if not membership_type.dues_schedule_template:
                frappe.throw(f"Membership Type '{membership_type.name}' must have a dues schedule template")
            template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)

            if not template.suggested_amount:
                frappe.throw(
                    f"Dues schedule template '{membership_type.dues_schedule_template}' must have a suggested_amount configured"
                )

            return {
                "amount": template.suggested_amount,
                "source": "template",
                "membership_type": membership_type.membership_type_name,
            }

        return {"amount": 0, "source": "none"}

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.FINANCIAL)
    def get_display_membership_fee(self):
        """Get membership fee for display with amendment status"""
        current_fee = self.get_current_membership_fee()

        # Check for pending amendments
        pending_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": self.name,
                "status": ["in", ["Draft", "Pending Approval", "Approved"]],
                "amendment_type": "Fee Change",
            },
            fields=["name", "status", "requested_amount", "effective_date", "reason"],
            order_by="creation desc",
            limit=1,
        )

        if pending_amendments:
            amendment = pending_amendments[0]
            return {
                "current_amount": current_fee["amount"],
                "display_amount": amendment["requested_amount"],
                "status": f"Pending - Effective {frappe.format_date(amendment['effective_date']) if amendment['effective_date'] else 'TBD'}",
                "amendment_status": amendment["status"],
                "amendment_id": amendment["name"],
                "reason": amendment["reason"],
                "source": "amendment_pending",
            }

        # No pending amendments, return current fee
        return {
            "current_amount": current_fee["amount"],
            "display_amount": current_fee["amount"],
            "status": "Current",
            "source": current_fee["source"],
            "reason": current_fee.get("reason"),
        }

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
        """Update the current chapter display field based on Chapter Member relationships with optimized queries"""
        try:
            chapters = self.get_current_chapters_optimized()

            if not chapters:
                # Use the custom field until the main field is fixed
                field_name = (
                    "current_chapter_display_temp"
                    if hasattr(self, "current_chapter_display_temp")
                    else "current_chapter_display"
                )
                setattr(self, field_name, '<p style="color: #888;"><em>No chapter assignment</em></p>')
                return

            # Build HTML using more efficient string operations
            html_items = ['<div class="member-chapters">']

            for chapter in chapters:
                chapter_display = chapter["chapter"]
                if chapter.get("region"):
                    chapter_display += f" ({chapter['region']})"

                status_badges = []
                if chapter.get("is_primary"):
                    status_badges.append('<span class="badge badge-success">Primary</span>')
                if chapter.get("is_board"):
                    status_badges.append('<span class="badge badge-info">Board Member</span>')
                if chapter.get("chapter_join_date"):
                    status_badges.append(
                        f'<span class="badge badge-light">Joined: {chapter["chapter_join_date"]}</span>'
                    )

                " ".join(status_badges) if status_badges else ""

                html_items.append(
                    """
                    <div class="chapter-item" style="margin-bottom: 8px; padding: 8px; border-left: 3px solid #007bff; background-color: #f8f9fa;">
                        <strong>{chapter_display}</strong>
                        {f'<br>{badges_html}' if badges_html else ''}
                    </div>
                """
                )

            html_items.append("</div>")

            # Use the custom field until the main field is fixed
            field_name = (
                "current_chapter_display_temp"
                if hasattr(self, "current_chapter_display_temp")
                else "current_chapter_display"
            )
            setattr(self, field_name, "".join(html_items))

        except Exception as e:
            frappe.log_error(f"Error updating chapter display: {str(e)}", "Member Chapter Display")
            self.current_chapter_display = '<p style="color: #dc3545;">Error loading chapter information</p>'

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
        """Update the other_members_at_address HTML field with data from get_other_members_at_address"""
        try:
            if not self.primary_address:
                html_content = ""
            else:
                # Get other members at the same address
                other_members = self.get_other_members_at_address()

                if not other_members or not isinstance(other_members, list) or len(other_members) == 0:
                    html_content = ""
                else:
                    # Format the data as HTML with cleaner styling (no blue container)
                    html_content = '<div class="other-members-container">'
                    html_content += f'<h6 class="text-muted"><i class="fa fa-users"></i> Other Members at Same Address ({len(other_members)})</h6>'

                    for member in other_members:
                        member_name = member.get("name", "")
                        member_full_name = member.get("full_name", "")

                        # Skip if member_name is empty - this prevents broken links
                        if not member_name or not member_name.strip():
                            frappe.log_error(
                                f"Empty member name in same address display: {member}", "Member DocType"
                            )
                            continue

                        status_color = {"Active": "success", "Pending": "warning", "Suspended": "danger"}.get(
                            member.get("status", ""), "secondary"
                        )

                        # Calculate age in years
                        age_text = ""
                        if member.get("birth_date"):
                            # Using standardized age calculation utility
                            from verenigingen.utils.validation_utilities import AgeValidator

                            age_years = int(AgeValidator.calculate_age(member["birth_date"]))
                            age_text = f"{age_years} years old"

                        # Validate member name format and existence using standardized validator
                        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

                        if not DocumentExistenceValidator.validate_document_exists(
                            "Member", member_name, throw_on_error=False
                        ):
                            frappe.log_error(
                                f"Invalid member reference in same address display: {member_name}",
                                "Member DocType",
                            )
                            continue

                        # Use Frappe's built-in escaping for security
                        import json

                        from frappe.utils import cstr

                        member_name_html = (
                            frappe.utils.cstr(member_name)
                            .replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                            .replace('"', "&quot;")
                            .replace("'", "&#39;")
                        )
                        member_full_name_html = (
                            frappe.utils.cstr(member_full_name)
                            .replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                            .replace('"', "&quot;")
                            .replace("'", "&#39;")
                        )
                        member_name_js = json.dumps(member_name)  # Proper JavaScript string escaping

                        html_content += '<div class="member-card" style="border-left: 3px solid #dee2e6; padding: 10px; margin: 8px 0; background: #f8f9fa;">'
                        html_content += f'<a href="/app/member/{member_name_html}" onclick="event.preventDefault(); frappe.set_route(\'Form\', \'Member\', {member_name_js}); return false;" style="font-weight: 600; color: #007bff; text-decoration: none; cursor: pointer;" title="View {member_full_name_html}">{member_full_name_html}</a><br>'
                        html_content += f'<span class="badge badge-{status_color}">{member.get("status", "Unknown")}</span>'

                        if member.get("member_since"):
                            html_content += (
                                f' <small class="text-muted">• Member since: {member["member_since"]}</small>'
                            )

                        if age_text:
                            html_content += f' <small class="text-muted">• {age_text}</small>'

                        html_content += "</div>"

                    html_content += "</div>"

            # Set the HTML content
            self.other_members_at_address = html_content

            # Optionally save directly to database
            if save_to_db and not self.get("__islocal"):
                frappe.db.set_value("Member", self.name, "other_members_at_address", html_content)
                frappe.db.commit()

        except Exception as e:
            frappe.log_error(
                f"Error updating other members at address display: {str(e)}", "Member Address Display"
            )
            html_content = '<p style="color: #dc3545;">Error loading address information</p>'
            self.other_members_at_address = html_content
            if save_to_db and not self.get("__islocal"):
                frappe.db.set_value("Member", self.name, "other_members_at_address", html_content)
                frappe.db.commit()

    def update_address_display(self):
        """Update the address_display HTML field with formatted address information"""
        try:
            if not self.primary_address:
                self.address_display = ""
                return

            # Get the address document
            address_doc = frappe.get_doc("Address", self.primary_address)

            # Format the address as HTML
            html_content = '<div class="address-display" style="background: #f8f9fa; border-left: 3px solid #28a745; padding: 10px; margin: 5px 0;">'

            if address_doc.address_line1:
                html_content += f"<strong>{address_doc.address_line1}</strong><br>"

            if address_doc.address_line2:
                html_content += f"{address_doc.address_line2}<br>"

            address_parts = []
            if address_doc.pincode:
                address_parts.append(address_doc.pincode)
            if address_doc.city:
                address_parts.append(address_doc.city)

            if address_parts:
                html_content += f'{" ".join(address_parts)}<br>'

            if address_doc.state:
                html_content += f"{address_doc.state}<br>"

            if address_doc.country:
                html_content += f'<small class="text-muted">{address_doc.country}</small>'

            html_content += "</div>"

            # Set the HTML content
            self.address_display = html_content

        except Exception as e:
            frappe.log_error(f"Error updating address display: {str(e)}", "Member Address Display")
            self.address_display = '<p style="color: #dc3545;">Error loading address information</p>'

    def add_fee_change_to_history(self, schedule_data):
        """Add a single fee change to history incrementally"""
        try:
            # Check if entry already exists for this schedule or amendment
            existing_idx = None
            for idx, row in enumerate(self.fee_change_history or []):
                row_schedule = getattr(row, "dues_schedule", None)
                row_amendment = getattr(row, "amendment_request", None)

                # Match by dues schedule
                if row_schedule and (
                    row_schedule == schedule_data.get("schedule_name")
                    or row_schedule == schedule_data.get("name")
                ):
                    existing_idx = idx
                    break

                # Match by amendment request
                if row_amendment and row_amendment == schedule_data.get("amendment_request"):
                    existing_idx = idx
                    break

            # Validate billing frequency - use "Custom" for unsupported frequencies
            valid_frequencies = ["Daily", "Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom"]
            billing_freq = (
                schedule_data.get("billing_frequency")
                if schedule_data.get("billing_frequency") in valid_frequencies
                else "Custom"
            )

            # Build entry data
            entry_data = {
                "change_date": schedule_data.get("change_date")
                or schedule_data.get("creation")
                or frappe.utils.now_datetime(),
                "dues_schedule": schedule_data.get("name") or schedule_data.get("schedule_name"),
                "billing_frequency": billing_freq,
                "old_dues_rate": schedule_data.get("old_dues_rate", 0),
                "new_dues_rate": schedule_data.get("dues_rate") or schedule_data.get("new_dues_rate"),
                "change_type": schedule_data.get("change_type", "Schedule Created"),
                "reason": schedule_data.get("reason")
                or f"Dues schedule: {schedule_data.get('schedule_name') or schedule_data.get('name')}",
                "changed_by": schedule_data.get("changed_by") or frappe.session.user or "Administrator",
                "amendment_request": schedule_data.get("amendment_request"),  # Support amendment tracking
            }

            if existing_idx is not None:
                # Update existing entry
                for key, value in entry_data.items():
                    if value is not None:  # Only update non-None values
                        setattr(self.fee_change_history[existing_idx], key, value)
            else:
                # Add new entry using append method (Frappe converts dict to child doc)
                self.append("fee_change_history", entry_data)

                # Keep only 50 most recent entries to prevent unlimited growth
                if len(self.fee_change_history) > 50:
                    # Remove oldest entries (at the end)
                    self.fee_change_history = self.fee_change_history[:50]

            # CORRECTED SECURE VERSION: Use secure operations with explicit permission validation
            result = secure_document_operation(
                operation="update_child_table",
                doc=self,
                justification=f"Add fee change to history for member {self.name}",
                required_permissions=["Member:write"],
                allow_system_user=True,  # Allow system user for automated financial data tracking
                bypass_validations=["link_validation"],  # Allow bypass of problematic chapter references
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to add fee change to history for member {self.name}: {'; '.join(result.errors)}",
                    "Fee Change History Manager",
                )
                return

        except Exception as e:
            frappe.log_error(
                f"Error adding fee change to history for member {self.name}: {str(e)}",
                "Fee Change History Update",
            )
            # Ensure method closure
            return

    def update_fee_change_in_history(self, schedule_data):
        """Update an existing fee change in history"""
        if not hasattr(self, "fee_change_history") or not self.fee_change_history:
            # If no history exists, just add it
            self.add_fee_change_to_history(schedule_data)
            return

        try:
            # Find the schedule in fee change history
            found = False
            schedule_name = schedule_data.get("name") or schedule_data.get("schedule_name")

            for _idx, row in enumerate(self.fee_change_history):
                if row.dues_schedule == schedule_name:
                    found = True
                    # Update the entry with new data
                    valid_frequencies = ["Daily", "Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom"]
                    billing_freq = (
                        schedule_data.get("billing_frequency")
                        if schedule_data.get("billing_frequency") in valid_frequencies
                        else "Custom"
                    )

                    # Update fields
                    row.change_date = schedule_data.get("change_date") or frappe.utils.now_datetime()
                    row.billing_frequency = billing_freq
                    row.old_dues_rate = schedule_data.get("old_dues_rate", row.old_dues_rate)
                    row.new_dues_rate = schedule_data.get("dues_rate") or schedule_data.get("new_dues_rate")
                    row.change_type = schedule_data.get("change_type", "Fee Adjustment")
                    row.reason = schedule_data.get("reason") or f"Updated: {schedule_name}"
                    row.changed_by = schedule_data.get("changed_by") or frappe.session.user or "Administrator"
                    break

            if not found:
                # Entry not in history, add it
                self.add_fee_change_to_history(schedule_data)
            else:
                # CORRECTED SECURE VERSION: Use secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="update_child_table",
                    doc=self,
                    justification=f"Update fee change in history for member {self.name}",
                    required_permissions=["Member:write"],
                    allow_system_user=True,  # Allow system user for automated financial data tracking
                    bypass_validations=["link_validation"],  # Allow bypass of problematic chapter references
                )

                if not result.success:
                    frappe.log_error(
                        f"Failed to update fee change in history for member {self.name}: {'; '.join(result.errors)}",
                        "Fee Change History Manager",
                    )
                    return

        except Exception as e:
            frappe.log_error(
                f"Error updating fee change in history for member {self.name}: {str(e)}",
                "Fee Change History Update",
            )

    def _update_donation_history(self):
        """Update donation history for this member"""
        if not (hasattr(self, "donor") and self.donor):
            return 0

        from verenigingen.utils.donation_history_manager import update_donor_history_table

        # This already does incremental updates - check if it made changes
        original_donation_count = len(getattr(self, "donation_history", []))
        update_donor_history_table(self.donor)
        # Reload to get updated donation history
        self.reload()
        new_donation_count = len(getattr(self, "donation_history", []))
        return abs(new_donation_count - original_donation_count)

    def _update_volunteer_expense_history(self):
        """Update volunteer expense history for this member"""
        if not (hasattr(self, "employee") and self.employee):
            return 0

        removed_count = 0
        updated_count = 0
        added_count = 0

        # Get the 20 most recent expense claims
        current_claims = frappe.get_all(
            "Expense Claim",
            filters={"employee": self.employee},
            fields=[
                "name",
                "employee",
                "posting_date",
                "total_claimed_amount",
                "total_sanctioned_amount",
                "status",
                "approval_status",
                "docstatus",
            ],
            order_by="posting_date desc",
            limit=20,
        )

        # Build a lookup of existing expense entries
        existing_expenses = {row.expense_claim: row for row in (self.volunteer_expenses or [])}
        current_claim_names = {claim.name for claim in current_claims}

        # Remove entries that are no longer in the top 20
        rows_to_remove = [
            idx
            for idx, row in enumerate(self.volunteer_expenses or [])
            if row.expense_claim not in current_claim_names
        ]

        # Remove in reverse order to maintain indices
        for idx in reversed(rows_to_remove):
            self.volunteer_expenses.pop(idx)
            removed_count += 1

        # Process each current claim
        for claim in current_claims:
            # Build what the row should look like using available data
            expected_row = self._build_lightweight_expense_entry(claim)

            if claim.name in existing_expenses:
                # Check if existing row needs updating
                existing_row = existing_expenses[claim.name]
                needs_update = any(
                    getattr(existing_row, field, None) != expected_value
                    for field, expected_value in expected_row.items()
                )

                if needs_update:
                    for field, expected_value in expected_row.items():
                        setattr(existing_row, field, expected_value)
                    updated_count += 1
            else:
                # Add new row directly (not via batch processor since we're already batching)
                try:
                    self.append("volunteer_expenses", expected_row)
                    added_count += 1
                except Exception as e:
                    frappe.log_error(
                        f"Failed to append volunteer expense {claim_name} for {self.name}: {str(e)}",
                        "Volunteer Expense Append Error",
                    )
                    # Continue processing other entries - don't break entire update
                    continue

        return removed_count + updated_count + added_count

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.ADMIN)
    def incremental_update_history_tables(self):
        """
        Incremental update of both donation and volunteer expense history tables.

        Now includes integrity checking and cleanup via HistoryIntegrityManager.
        """
        try:
            changes_made = False
            donation_changes = 0
            expense_changes = 0
            cleanup_removed = 0

            # STEP 1: Clean broken volunteer expense entries (if employee linked)
            if hasattr(self, "employee") and self.employee:
                from verenigingen.utils.member_history_integrity import HistoryIntegrityManager

                manager = HistoryIntegrityManager(self)
                cleanup_stats = manager.cleanup_volunteer_expense_history()
                cleanup_removed = cleanup_stats["removed"]

                if cleanup_removed > 0:
                    changes_made = True

            # STEP 2: Update donation history if donor is linked
            donation_changes = self._update_donation_history()
            if donation_changes > 0:
                changes_made = True

            # STEP 3: Update volunteer expense history if employee is linked
            expense_changes = self._update_volunteer_expense_history()
            if expense_changes > 0:
                changes_made = True

            # Only save if something actually changed
            if changes_made:
                # Suppress version tracking for automated history updates
                self.flags.ignore_version = True
                # Skip link validation for automated system updates
                self.flags.ignore_links = True
                self.save()

            return {
                "overall_success": True,
                "volunteer_expenses": {
                    "success": True,
                    "count": expense_changes,
                    "cleaned": cleanup_removed,
                },
                "donations": {"success": True, "count": donation_changes},
                "message": f"Incremental update: {donation_changes} donation changes, {expense_changes} expense changes, {cleanup_removed} broken entries cleaned",
            }

        except Exception as e:
            frappe.log_error(
                f"Error in incremental history update for member {self.name}: {str(e)}",
                "Incremental History Update",
            )
            return {
                "overall_success": False,
                "volunteer_expenses": {"success": False, "error": str(e)},
                "donations": {"success": False, "error": str(e)},
                "message": f"Error updating history tables: {str(e)}",
            }

    def _build_lightweight_expense_entry(self, claim_data):
        """
        Build expense history entry from claim data without loading full document.
        Uses data already available from frappe.get_all() call.
        """
        try:
            # Get volunteer information
            volunteer_name = None
            if hasattr(claim_data, "employee") or "employee" in claim_data:
                employee = getattr(claim_data, "employee", claim_data.get("employee"))
                if employee:
                    # First try to find volunteer by employee_id field and member link
                    volunteer_name = frappe.db.get_value(
                        "Volunteer", {"employee_id": employee, "member": self.name}, "name"
                    )

                    # Fallback: if not found, try without member filter
                    if not volunteer_name:
                        volunteer_name = frappe.db.get_value("Volunteer", {"employee_id": employee}, "name")

            # Get basic expense information
            expense_name = getattr(claim_data, "name", claim_data.get("name"))
            expense_status = getattr(claim_data, "status", claim_data.get("status", "Draft"))
            docstatus = getattr(claim_data, "docstatus", claim_data.get("docstatus", 0))
            approval_status = getattr(claim_data, "approval_status", claim_data.get("approval_status"))

            # Apply status logic based on docstatus and approval_status
            if docstatus == 0:
                expense_status = "Draft"
            elif docstatus == 1:
                if approval_status == "Rejected":
                    expense_status = "Rejected"
                # Otherwise use the status from the expense claim (Paid/Unpaid/Submitted/etc.)

            # Check for existing payment to determine payment_status
            payment_entry = None
            payment_date = None
            paid_amount = 0
            payment_method = None
            payment_status = "Pending"

            # Look for payment entries referencing this expense claim
            payment_refs = frappe.get_all(
                "Payment Entry Reference",
                filters={"reference_doctype": "Expense Claim", "reference_name": expense_name},
                fields=["parent", "allocated_amount"],
            )

            if payment_refs:
                # Get the most recent payment
                payment_entries = frappe.get_all(
                    "Payment Entry",
                    filters={"name": ["in", [ref.parent for ref in payment_refs]], "docstatus": 1},
                    fields=["name", "posting_date", "paid_amount", "mode_of_payment"],
                    order_by="posting_date desc",
                )

                if payment_entries:
                    payment_entry = payment_entries[0].name
                    payment_date = payment_entries[0].posting_date
                    paid_amount = payment_entries[0].paid_amount
                    payment_method = payment_entries[0].mode_of_payment
                    payment_status = "Paid"

            return {
                "expense_claim": expense_name,
                "volunteer": volunteer_name,
                "posting_date": getattr(claim_data, "posting_date", claim_data.get("posting_date")),
                "total_claimed_amount": getattr(
                    claim_data, "total_claimed_amount", claim_data.get("total_claimed_amount", 0)
                ),
                "total_sanctioned_amount": getattr(
                    claim_data, "total_sanctioned_amount", claim_data.get("total_sanctioned_amount", 0)
                ),
                "status": expense_status,
                "payment_entry": payment_entry,
                "payment_date": payment_date,
                "paid_amount": paid_amount,
                "payment_method": payment_method,
                "payment_status": payment_status,
            }

        except Exception as e:
            frappe.log_error(
                f"Error building lightweight expense entry for {getattr(claim_data, 'name', 'unknown')}: {str(e)}",
                "Lightweight Expense Entry Build Error",
            )
            # Return minimal entry on error
            return {
                "expense_claim": getattr(claim_data, "name", claim_data.get("name")),
                "volunteer": None,
                "posting_date": getattr(claim_data, "posting_date", claim_data.get("posting_date")),
                "total_claimed_amount": getattr(
                    claim_data, "total_claimed_amount", claim_data.get("total_claimed_amount", 0)
                ),
                "total_sanctioned_amount": getattr(
                    claim_data, "total_sanctioned_amount", claim_data.get("total_sanctioned_amount", 0)
                ),
                "status": getattr(claim_data, "status", claim_data.get("status", "Draft")),
                "payment_entry": None,
                "payment_date": None,
                "paid_amount": 0,
                "payment_method": None,
                "payment_status": "Draft",  # FIXED: Use valid payment status instead of "Unknown"
            }

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
@high_security_api(operation_type=OperationType.MEMBER_DATA)
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
    """
    Manually assign a member ID to a member who doesn't have one yet.
    This can be used for approved applications or existing members without IDs.
    """
    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("Insufficient permissions to assign member ID"))

    # Only allow System Manager and Verenigingen Staff roles to manually assign member IDs
    allowed_roles = ["System Manager", "Verenigingen Staff"]
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(role in user_roles for role in allowed_roles):
        frappe.throw(_("Only System Managers and Verenigingen Staffs can manually assign member IDs"))

    try:
        member = frappe.get_doc("Member", member_name)

        # Check if member already has an ID
        if member.member_id:
            return {"success": False, "message": _("Member already has ID: {0}").format(member.member_id)}

        # For application members, they should be approved first
        if member.is_application_member() and not member.should_have_member_id():
            return {
                "success": False,
                "message": _(
                    "Application member must be approved before assigning member ID. Current status: {0}"
                ).format(member.application_status),
            }

        # Generate and assign member ID
        from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

        next_id = MemberIDManager.get_next_member_id()
        member.member_id = str(next_id)

        # Save the member
        member.save()

        frappe.msgprint(_("Member ID {0} assigned successfully to {1}").format(next_id, member.full_name))

        return {
            "success": True,
            "member_id": str(next_id),
            "message": _("Member ID {0} assigned successfully").format(next_id),
        }

    except Exception as e:
        frappe.log_error(f"Error assigning member ID to {member_name}: {str(e)}")
        return {"success": False, "message": _("Error assigning member ID: {0}").format(str(e))}


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

        deactivated_count = 0
        deactivated_mandates = []

        for mandate_data in active_mandates:
            # Only deactivate mandates with different IBAN
            if mandate_data.iban != new_iban:
                mandate = frappe.get_doc("SEPA Mandate", mandate_data.name)

                # Deactivate the mandate
                mandate.status = "Cancelled"
                mandate.is_active = 0
                mandate.cancellation_date = today()
                mandate.cancellation_reason = f"IBAN changed from {mandate.iban} to {new_iban}"

                mandate.save()

                deactivated_count += 1
                deactivated_mandates.append({"mandate_id": mandate.mandate_id, "old_iban": mandate.iban})

                frappe.logger().info(
                    f"Deactivated SEPA mandate {mandate.mandate_id} for member {member} due to IBAN change"
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
    """Assign member IDs to all members who should have them but don't"""
    members_without_ids = frappe.get_all(
        "Member",
        filters={"member_id": ["is", "not set"]},
        fields=["name", "application_status", "application_id", "full_name"],
    )

    assigned_count = 0
    for member_data in members_without_ids:
        try:
            member = frappe.get_doc("Member", member_data.name)
            if member.should_have_member_id():
                member.ensure_member_id()
                assigned_count += 1
                frappe.logger().info(f"Assigned member ID {member.member_id} to {member.full_name}")
        except Exception as e:
            frappe.logger().error(f"Failed to assign member ID to {member_data.name}: {str(e)}")

    return {
        "total_checked": len(members_without_ids),
        "assigned": assigned_count,
        "message": f"Assigned member IDs to {assigned_count} out of {len(members_without_ids)} members",
    }


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
    """Debug why member ID assignment is failing"""
    try:
        member = frappe.get_doc("Member", member_name)

        debug_info = {
            "member_name": member.name,
            "current_member_id": getattr(member, "member_id", None),
            "has_member_id": bool(getattr(member, "member_id", None)),
            "is_application_member": member.is_application_member(),
            "application_id": getattr(member, "application_id", None),
            "application_status": getattr(member, "application_status", None),
            "status": getattr(member, "status", None),
            "should_have_member_id": member.should_have_member_id(),
            "can_assign_id": not member.member_id and member.should_have_member_id(),
        }

        return debug_info

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_member_user_account(member_name, send_welcome_email=True):
    """Create a user account for a member to access portal pages"""
    try:
        # Get the member document
        member = frappe.get_doc("Member", member_name)

        # Check if user already exists
        if member.user:
            return {
                "success": False,
                "message": _("User account already exists for this member"),
                "user": member.user,
            }

        # Check if a user with this email already exists
        existing_user = frappe.db.get_value("User", {"email": member.email}, "name")
        if existing_user:
            # Link the existing user to the member
            member.user = existing_user
            member_result = secure_document_operation(
                operation="save",
                doc=member,
                justification=f"Link existing user {existing_user} to member {member.name}",
                required_permissions=["Member:write"],
            )

            if not member_result.success:
                frappe.logger().error(f"Failed to link user to member: {'; '.join(member_result.errors)}")
                frappe.throw(_("Failed to link user to member: {0}").format("; ".join(member_result.errors)))

            # Add member roles to existing user
            add_member_roles_to_user(existing_user)

            return {
                "success": True,
                "message": _("Linked existing user account to member"),
                "user": existing_user,
                "action": "linked_existing",
            }

        # Create new user
        user = frappe.new_doc("User")
        user.email = member.email
        user.first_name = member.first_name or ""
        user.last_name = member.last_name or ""
        user.full_name = member.full_name
        from verenigingen.utils.boolean_utils import cbool

        user.send_welcome_email = cbool(send_welcome_email)
        user.user_type = "System User"
        user.enabled = 1

        user_result = secure_document_operation(
            operation="insert",
            doc=user,
            justification=f"Automated user creation for member {member.name}",
            required_permissions=["User:create"],
        )

        if not user_result.success:
            frappe.logger().error(f"Failed to create user: {'; '.join(user_result.errors)}")
            frappe.throw(_("Failed to create user: {0}").format("; ".join(user_result.errors)))

        # Set allowed modules for member users
        set_member_user_modules(user.name)

        # Add member-specific roles
        add_member_roles_to_user(user.name)

        # Link user to member
        member.user = user.name
        member_link_result = secure_document_operation(
            operation="save",
            doc=member,
            justification=f"Link newly created user {user.name} to member {member.name}",
            required_permissions=["Member:write"],
        )

        if not member_link_result.success:
            frappe.logger().error(
                f"Failed to link new user to member: {'; '.join(member_link_result.errors)}"
            )
            frappe.throw(
                _("Failed to link new user to member: {0}").format("; ".join(member_link_result.errors))
            )

        frappe.logger().info(f"Created user account {user.name} for member {member.name}")

        return {
            "success": True,
            "message": _("User account created successfully"),
            "user": user.name,
            "action": "created_new",
        }

    except Exception as e:
        frappe.log_error(f"Error creating user account for member {member_name}: {str(e)}")
        return {"success": False, "error": str(e)}


def add_member_roles_to_user(user_name):
    """Add appropriate role profile for a member user to access portal pages"""
    try:
        # Check if user has permission to modify roles
        if not frappe.has_permission("User", "write"):
            frappe.throw(_("Insufficient permissions to modify user roles"))

        # Check if Verenigingen Member role profile exists
        role_profile_name = "Verenigingen Member"
        if not frappe.db.exists("Role Profile", role_profile_name):
            frappe.logger().warning(
                f"Role Profile {role_profile_name} does not exist. Creating basic roles manually."
            )
            # Fallback to individual role assignment
            return _assign_individual_member_roles(user_name)

        # Add role profile to user
        user = frappe.get_doc("User", user_name)

        # Clear existing roles first to avoid conflicts with role profile
        user.roles = []

        # Assign the role profile
        user.role_profile_name = role_profile_name

        # Ensure user is enabled
        if not user.enabled:
            user.enabled = 1

        # Save with proper permissions (no bypass)
        user.save()
        frappe.logger().info(f"Assigned role profile '{role_profile_name}' to user {user_name}")

        return user.name

    except Exception as e:
        frappe.log_error(f"Error adding roles to user {user_name}: {str(e)}")
        return None


def _assign_individual_member_roles(user_name):
    """Fallback method to assign individual roles when role profile is not available"""
    try:
        # Check permissions
        if not frappe.has_permission("User", "write"):
            frappe.throw(_("Insufficient permissions to modify user roles"))

        # Define the roles that members need for portal access
        member_roles = [
            "Verenigingen Member",  # Primary member role for all member access
            "All",  # Standard role for basic system access
        ]

        # Check if Verenigingen Member role exists, create if not
        if not frappe.db.exists("Role", "Verenigingen Member"):
            create_verenigingen_member_role()

        # Add roles to user
        user = frappe.get_doc("User", user_name)

        # Clear existing roles first to avoid conflicts
        user.roles = []

        for role in member_roles:
            if not frappe.db.exists("Role", role):
                frappe.logger().warning(f"Role {role} does not exist, skipping")
                continue
            # Always add the role since we cleared roles above
            user.append("roles", {"role": role})

        # Ensure user is enabled
        if not user.enabled:
            user.enabled = 1

        # Save with proper permissions (no bypass)
        user.save()
        frappe.logger().info(f"Assigned individual roles to user {user_name}: {member_roles}")

        return user.name

    except Exception as e:
        frappe.log_error(f"Error assigning individual member roles to user {user_name}: {str(e)}")
        raise


# Removed create_member_portal_role - consolidated into Verenigingen Member


def create_verenigingen_member_role():
    """Create the Verenigingen Member role for consolidated member access"""
    try:
        role = frappe.new_doc("Role")
        role.role_name = "Verenigingen Member"
        role.desk_access = 0  # Portal users don't need desk access
        role.is_custom = 1  # This is a custom role for the app
        role_result = secure_document_operation(
            operation="insert",
            doc=role,
            justification="Create Verenigingen Member role for member portal access",
            required_permissions=["Role:create"],
        )

        if not role_result.success:
            frappe.logger().error(
                f"Failed to create Verenigingen Member role: {'; '.join(role_result.errors)}"
            )
            frappe.throw(
                _("Failed to create Verenigingen Member role: {0}").format("; ".join(role_result.errors))
            )

        frappe.logger().info(
            "Created Verenigingen Member role (consolidated from Member Portal User and Member)"
        )
        return role.name

    except Exception as e:
        frappe.log_error(f"Error creating Verenigingen Member role: {str(e)}")
        return None


def set_member_user_modules(user_name):
    """Set allowed modules for member users - restrict to relevant modules only"""
    try:
        # Define modules that members should have access to
        allowed_modules = [
            "Verenigingen",  # Main app module
            "Core",  # Essential Frappe core functionality
            "Desk",  # Basic desk access
            "Home",  # Home page access
        ]

        user = frappe.get_doc("User", user_name)

        # Clear existing module access and set only allowed ones
        user.set("block_modules", [])

        # Get all available modules
        all_modules = frappe.get_all("Module Def", fields=["name"])

        # Block all modules except the allowed ones
        for module in all_modules:
            if module.name not in allowed_modules:
                user.append("block_modules", {"module": module.name})

        module_result = secure_document_operation(
            operation="save",
            doc=user,
            justification=f"Set module restrictions for user {user_name}",
            required_permissions=["User:write"],
        )

        if not module_result.success:
            frappe.logger().error(f"Failed to set module restrictions: {'; '.join(module_result.errors)}")
            frappe.throw(_("Failed to set module restrictions: {0}").format("; ".join(module_result.errors)))
        frappe.logger().info(f"Set module restrictions for user {user_name}")

    except Exception as e:
        frappe.log_error(f"Error setting module restrictions for user {user_name}: {str(e)}")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def check_donor_exists(member_name):
    """Check if a donor record exists for this member"""
    from verenigingen.services.member.donor import DonorManagementService

    return DonorManagementService.check_donor_exists(member_name)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_donor_from_member(member_name):
    """Create a donor record from member information"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Check if donor already exists
        existing_check = check_donor_exists(member_name)
        if existing_check.get("exists"):
            return {
                "success": False,
                "message": _("Donor record already exists for this member"),
                "donor_name": existing_check.get("donor_name"),
            }

        # Create donor record
        donor = frappe.new_doc("Donor")

        # Copy basic information from member
        donor.donor_name = member.full_name
        donor.donor_email = member.email

        # Set mandatory fields (only donor_name, donor_type, and donor_email are required)
        donor.donor_type = "Individual"

        # Set optional fields only if they exist in the DocType and have values
        if member.full_name:
            donor.contact_person = member.full_name

        # Set phone only if member has a phone number (phone is NOT required in Donor DocType)
        if member.contact_number and member.contact_number.strip():
            # If the number doesn't start with +, assume it's Dutch and add +31
            phone_number = member.contact_number.replace(" ", "")  # Remove spaces for validation
            if not phone_number.startswith("+"):
                # Check if it's a Dutch mobile number (starts with 06) or landline
                if phone_number.startswith("06") or phone_number.startswith("0"):
                    phone_number = "+31" + phone_number[1:]  # Replace leading 0 with +31
                else:
                    phone_number = "+31" + phone_number  # Add +31 prefix
            donor.phone = phone_number
        # No else clause - phone is optional, leave it empty if no phone number

        # Set donor category if available
        donor.donor_category = "Regular Donor"

        # Copy address information if available (using the 'address' field that exists in DocType)
        if member.primary_address:
            try:
                address_doc = frappe.get_doc("Address", member.primary_address)
                # Use the single 'address' field that exists in the DocType
                address_parts = []
                if address_doc.address_line1:
                    address_parts.append(address_doc.address_line1)
                if address_doc.address_line2:
                    address_parts.append(address_doc.address_line2)
                if address_doc.city:
                    address_parts.append(address_doc.city)
                if address_doc.pincode:
                    address_parts.append(address_doc.pincode)
                if address_doc.country:
                    address_parts.append(address_doc.country)
                donor.address = ", ".join(address_parts)
            except Exception as addr_e:
                frappe.logger().warning(f"Could not copy address from member {member_name}: {str(addr_e)}")

        # Link to the member record
        donor.member = member.name

        # Secure donor creation with explicit permission validation
        donor_result = secure_document_operation(
            operation="insert",
            doc=donor,
            justification=f"Automated donor creation for member {member.name}",
            required_permissions=["Donor:create"],
        )

        if not donor_result.success:
            return {
                "success": False,
                "error": "; ".join(donor_result.errors),
                "message": _("Failed to create donor record: {0}").format("; ".join(donor_result.errors)),
            }

        # Link the customer record if it exists
        if member.customer:
            try:
                # Update customer record to link to donor
                customer_doc = frappe.get_doc("Customer", member.customer)
                if hasattr(customer_doc, "donor"):
                    customer_doc.donor = donor.name

                    # Secure customer update with explicit permission validation
                    customer_result = secure_document_operation(
                        operation="save",
                        doc=customer_doc,
                        justification=f"Link customer {member.customer} to donor {donor.name}",
                        required_permissions=["Customer:write"],
                    )

                    if not customer_result.success:
                        frappe.logger().warning(
                            f"Could not link customer {member.customer} to donor {donor.name}: "
                            f"{'; '.join(customer_result.errors)}"
                        )
            except Exception as cust_e:
                frappe.logger().warning(f"Could not link customer to donor: {str(cust_e)}")

        frappe.logger().info(f"Created donor record {donor.name} for member {member.name}")

        return {
            "success": True,
            "message": _("Donor record created successfully. Member can now receive donation receipts."),
            "donor_name": donor.name,
        }

    except Exception as e:
        # Very short error message to avoid log truncation
        frappe.log_error(f"Donor creation failed: {str(e)[:50]}")
        return {
            "success": False,
            "error": str(e),
            "message": _("Failed to create donor record: {0}").format(str(e)),
        }

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

    def _load_volunteer_details_html(self):
        """Load volunteer details HTML for display"""
        try:
            # Get linked volunteer record
            volunteer = get_volunteer_for_member(self.name)
            if not volunteer:
                self.volunteer_details_html = '<div class="text-muted">No volunteer record linked</div>'
                return

            volunteer_doc = frappe.get_doc("Volunteer", volunteer)

            # Build HTML content
            html_parts = []
            html_parts.append('<div class="volunteer-details">')
            html_parts.append(f"<p><strong>Volunteer ID: </strong> {volunteer}</p>")
            html_parts.append(f"<p><strong>Volunteer Name: </strong> {volunteer_doc.volunteer_name}</p>")

            if volunteer_doc.start_date:
                html_parts.append(
                    f"<p><strong>Start Date: </strong> {frappe.utils.format_date(volunteer_doc.start_date)}</p>"
                )

            if volunteer_doc.status:
                status_color = {"Active": "success", "Inactive": "secondary", "New": "info"}.get(
                    volunteer_doc.status, "secondary"
                )
                html_parts.append(
                    f'<p><strong>Status: </strong> <span class="badge badge-{status_color}">{volunteer_doc.status}</span></p>'
                )

            # Add link to volunteer record
            html_parts.append(
                f'<p><a href="/app/volunteer/{volunteer}" class="btn btn-sm btn-default">View Volunteer Record</a></p>'
            )

            html_parts.append("</div>")

            self.volunteer_details_html = "\n".join(html_parts)

        except Exception as e:
            frappe.log_error(f"Error loading volunteer details HTML for member {self.name}: {str(e)}")
            self.volunteer_details_html = (
                f'<div class="text-danger">Error loading volunteer details: {str(e)}</div>'
            )

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
@development_only_api(operation_type=OperationType.UTILITY)
def test_dues_schedule_query(member_name):
    """Test the exact query used in JavaScript"""
    try:
        filters = {"member": member_name, "is_template": 0, "status": ["in", ["Active", "Paused"]]}
        result = frappe.db.get_value(
            "Membership Dues Schedule",
            filters,
            ["name", "dues_rate", "billing_frequency", "status"],
            as_dict=True,
        )
        return {"query_result": result, "filters_used": filters}
    except Exception as e:
        return {"error": str(e), "filters_used": filters}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_button_conditions(member_name):
    """Debug what buttons should appear for a member"""
    try:
        member = frappe.get_doc("Member", member_name)

        # Check various conditions
        has_customer = bool(getattr(member, "customer", None))
        has_user = bool(getattr(member, "user", None))
        has_email = bool(getattr(member, "email", None))

        # Check for volunteer
        has_volunteer = bool(frappe.db.exists("Volunteer", {"member": member_name}))

        # Check for active membership
        has_active_membership = bool(
            frappe.db.exists(
                "Membership",
                {"member": member_name, "status": ["in", ["Active", "Pending"]], "docstatus": ["!=", 2]},
            )
        )

        # Check for donor
        has_donor = bool(frappe.db.exists("Donor", {"linked_member": member_name}))

        return {
            "member_name": member_name,
            "status": member.status,
            "docstatus": member.docstatus,
            "has_customer": has_customer,
            "has_user": has_user,
            "has_email": has_email,
            "has_volunteer": has_volunteer,
            "has_active_membership": has_active_membership,
            "has_donor": has_donor,
            "expected_buttons": {
                "create_customer": not has_customer,
                "create_user": has_email and not has_user,
                "create_volunteer": not has_volunteer,
                "create_membership": not has_active_membership,
                "create_donor": not has_donor,
                "dues_management": True,  # Always show if script works
            },
        }
    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_member_status(member_name):
    """Debug member status for button investigation"""
    try:
        member = frappe.get_doc("Member", member_name)
        return {
            "name": member.name,
            "status": member.status,
            "application_status": getattr(member, "application_status", None),
            "customer": getattr(member, "customer", None),
            "user": getattr(member, "user", None),
            "docstatus": member.docstatus,
            "payment_method": getattr(member, "payment_method", None),
        }
    except Exception as e:
        return {"error": str(e)}


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
@high_security_api(operation_type=OperationType.FINANCIAL)
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
    """Refresh fee change history from dues schedules with integrity checking (atomic approach)"""
    try:
        # Get the member document - use get_doc with for_update to handle concurrency
        member_doc = frappe.get_doc("Member", member_name, for_update=True)

        # STEP 1: Clean broken history entries (all types for consistency)
        from verenigingen.utils.member_history_integrity import cleanup_member_history

        cleanup_result = cleanup_member_history(member_doc)
        # Extract fee-specific stats for backward compatibility
        cleanup_stats = {
            "removed": cleanup_result["fee_history"]["removed"],
            "reasons": {"total": cleanup_result["fee_history"]["removed"]},
            "errors": cleanup_result["fee_history"]["errors"],
        }

        # Get all dues schedules for this member
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "schedule_name", "dues_rate", "billing_frequency", "status", "creation"],
            order_by="creation",
        )

        # Get existing fee change history entries - track by both schedule and amendment
        existing_entries_by_schedule = {
            row.dues_schedule: row for row in member_doc.fee_change_history or [] if row.dues_schedule
        }
        existing_entries_by_amendment = {
            row.amendment_request: row for row in member_doc.fee_change_history or [] if row.amendment_request
        }

        # STEP 2: Get all applied amendments for this member
        applied_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={"member": member_name, "status": "Applied"},
            fields=[
                "name",
                "effective_date",
                "requested_amount",
                "current_amount",
                "reason",
                "applied_date",
                "applied_by",
            ],
            order_by="effective_date, applied_date",
        )

        # Process amendments first to capture all changes
        for amendment in applied_amendments:
            amendment_name = amendment.name

            # Check if we already have an entry for this amendment
            if amendment_name not in existing_entries_by_amendment:
                # Add new amendment entry
                amendment_data = {
                    "amendment_request": amendment_name,
                    "dues_rate": amendment.requested_amount,
                    "old_dues_rate": amendment.current_amount or 0,
                    "change_type": "Fee Adjustment",
                    "reason": f"Amendment: {amendment.reason}"
                    if amendment.reason
                    else f"Amendment {amendment_name}",
                    "change_date": amendment.applied_date or amendment.effective_date,
                    "changed_by": amendment.applied_by or "Administrator",
                }
                member_doc.add_fee_change_to_history(amendment_data)

        # STEP 3: Process schedules (for initial schedule creation only)
        for schedule in dues_schedules:
            schedule_name = schedule.name

            # Check if entry already exists for this schedule
            if schedule_name in existing_entries_by_schedule:
                # Update existing entry if needed
                existing_entry = existing_entries_by_schedule[schedule_name]

                # Check if update is needed (compare key fields)
                needs_update = (
                    existing_entry.new_dues_rate != schedule.dues_rate
                    or existing_entry.billing_frequency != schedule.billing_frequency
                    or existing_entry.reason != f"Dues schedule: {schedule.schedule_name or schedule.name}"
                )

                if needs_update:
                    # Use atomic update method
                    schedule_data = {
                        "name": schedule.name,
                        "schedule_name": schedule.schedule_name,
                        "dues_rate": schedule.dues_rate,
                        "billing_frequency": schedule.billing_frequency,
                        "old_dues_rate": existing_entry.old_dues_rate,  # Preserve old rate
                        "change_type": "Fee Adjustment",
                        "reason": f"Dues schedule: {schedule.schedule_name or schedule.name}",
                        "change_date": frappe.utils.now_datetime(),  # Update timestamp
                        "changed_by": frappe.session.user or "Administrator",
                    }
                    member_doc.update_fee_change_in_history(schedule_data)
            else:
                # Add new entry using atomic method (initial schedule creation only)
                schedule_data = {
                    "name": schedule.name,
                    "schedule_name": schedule.schedule_name,
                    "dues_rate": schedule.dues_rate,
                    "billing_frequency": schedule.billing_frequency,
                    "creation": schedule.creation,
                    "old_dues_rate": 0,  # First schedule for this member
                    "change_type": "Schedule Created",
                    "reason": f"Dues schedule: {schedule.schedule_name or schedule.name}",
                    "changed_by": frappe.session.user or "Administrator",
                }
                member_doc.add_fee_change_to_history(schedule_data)

        # Fee history updates are administrative operations that preserve audit trail
        member_doc.flags.ignore_validate_update_after_submit = True  # JUSTIFIED: Fee history update

        fee_history_result = secure_document_operation(
            operation="update_child_table",
            doc=member_doc,
            justification=f"Update fee change history for member {member_doc.name}",
            required_permissions=["Member:write"],
            allow_system_user=False,  # Require explicit user permissions for financial data
            bypass_validations=["link_validation"],  # Allow bypass of problematic chapter references
        )

        if not fee_history_result.success:
            frappe.logger().error(
                f"Failed to update fee change history: {'; '.join(fee_history_result.errors)}"
            )
            frappe.throw(
                _("Failed to update fee change history: {0}").format("; ".join(fee_history_result.errors))
            )

        # Commit the changes to ensure they're saved
        frappe.db.commit()

        return {
            "success": True,
            "message": f"Fee change history refreshed for {member_name} - {len(applied_amendments)} amendments + {len(dues_schedules)} schedules processed, {cleanup_stats['removed']} broken entries cleaned",
            "history_count": len(applied_amendments) + len(dues_schedules),
            "reload_doc": True,  # Signal to reload the document
            "amendments_found": len(applied_amendments),
            "dues_schedules_found": len(dues_schedules),
            "removed_entries": cleanup_stats["removed"],
            "cleanup_details": cleanup_stats,
            "method": "atomic_with_amendments",
        }

    except Exception as e:
        error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)  # Truncate long errors
        frappe.log_error(f"Fee change history error: {error_msg}", "Fee History Refresh")
        return {"success": False, "message": f"Error: {error_msg}"}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_amendment_filtering():
    """Test the new amendment filtering logic"""

    # Test with a real member that might have amendments
    member_name = "Assoc-Member-2025-07-0017"

    # Import the function
    from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
        get_member_pending_contribution_amendments,
    )

    # Get amendments with new filtering
    amendments = get_member_pending_contribution_amendments(member_name)

    print(f"Found {len(amendments)} pending amendments for {member_name}")

    # Also test the raw query to see what would be returned without filtering
    raw_amendments = frappe.get_all(
        "Contribution Amendment Request",
        filters={"member": member_name, "status": ["in", ["Draft", "Pending Approval", "Approved"]]},
        fields=["name", "status", "effective_date", "creation"],
        order_by="creation desc",
    )

    print(f"Raw query returned {len(raw_amendments)} amendments")

    # Show the difference
    for amendment in raw_amendments:
        in_filtered = any(a.name == amendment.name for a in amendments)
        status_str = "✓ INCLUDED" if in_filtered else "✗ FILTERED OUT"

        if amendment.effective_date:
            date_status = f"(effective: {amendment.effective_date})"
            if amendment.status == "Approved":
                # using getdate, today from top-level import

                is_future = getdate(amendment.effective_date) >= getdate(today())
                date_status += f" - {'FUTURE' if is_future else 'PAST'}"
        else:
            date_status = "(no effective date)"

        print(f"  {status_str}: {amendment.name} - {amendment.status} {date_status}")

    return {
        "member": member_name,
        "filtered_count": len(amendments),
        "raw_count": len(raw_amendments),
        "success": True,
    }


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_automatic_fee_history_update(member_name="Assoc-Member-2025-07-0017"):
    """Test that fee change history updates automatically when dues schedules are modified"""

    print(f"Testing automatic fee change history update for {member_name}")

    # Get current fee change history count
    current_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
    print(f"Current fee change history count: {current_count}")

    # Get member's current active dues schedule
    active_schedule = frappe.db.get_value(
        "Membership Dues Schedule",
        {"member": member_name, "status": "Active"},
        ["name", "dues_rate"],
        as_dict=True,
    )

    if not active_schedule:
        return {"success": False, "message": "No active dues schedule found for member"}

    print(f"Current active schedule: {active_schedule.name} with rate: €{active_schedule.dues_rate}")

    # Update the dues rate to trigger the automatic fee change history update
    schedule_doc = frappe.get_doc("Membership Dues Schedule", active_schedule.name)
    old_rate = schedule_doc.dues_rate
    new_rate = max(old_rate + 5.00, 10.00)  # Add €5 or set to €10, whichever is higher

    print(f"Changing dues rate from €{old_rate} to €{new_rate}")

    # Update the schedule
    schedule_doc.dues_rate = new_rate
    schedule_doc.save()

    # Check if fee change history was updated automatically
    new_count = frappe.db.count("Member Fee Change History", {"parent": member_name})
    print(f"New fee change history count: {new_count}")

    success = new_count > current_count

    if success:
        print("✅ SUCCESS: Fee change history was updated automatically!")

        # Get the latest entry
        latest_entry = frappe.db.get_value(
            "Member Fee Change History",
            {"parent": member_name},
            ["change_date", "old_dues_rate", "new_dues_rate", "change_type"],
            as_dict=True,
            order_by="idx DESC",
        )

        if latest_entry:
            print(
                f"Latest entry: {latest_entry.change_type} - €{latest_entry.old_dues_rate} → €{latest_entry.new_dues_rate}"
            )
    else:
        print("❌ FAILED: Fee change history was not updated automatically")

    # Revert the change
    schedule_doc.dues_rate = old_rate
    schedule_doc.save()
    print(f"Reverted dues rate back to €{old_rate}")

    return {
        "success": success,
        "current_count": current_count,
        "new_count": new_count,
        "test_completed": True,
    }


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_fee_history_functionality(member_name="Assoc-Member-2025-07-0030"):
    """Test function to validate fee change history functionality"""
    try:
        # Call the refresh function
        result = refresh_fee_change_history(member_name)

        # Get member data
        member = frappe.get_doc("Member", member_name)

        # Get dues schedules
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name},
            fields=["name", "schedule_name", "dues_rate", "status"],
        )

        return {
            "refresh_result": result,
            "member_name": member_name,
            "fee_change_history_count": len(member.fee_change_history or []),
            "dues_schedules_count": len(dues_schedules),
            "dues_schedules": dues_schedules,
            "fee_change_history": [
                {
                    "change_date": entry.change_date,
                    "change_type": entry.change_type,
                    "old_rate": entry.old_dues_rate,
                    "new_rate": entry.new_dues_rate,
                    "reason": entry.reason,
                    "dues_schedule": entry.dues_schedule,
                }
                for entry in (member.fee_change_history or [])
            ],
        }

    except Exception as e:
        frappe.log_error(f"Test fee history error: {str(e)}", "Test Fee History")
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def fix_existing_member_workflow_status():
    """Fix application_status for existing active members who shouldn't be in workflow states"""
    try:
        # Find all members with status='Active' but application_status != 'Active'
        members_to_fix = frappe.db.sql(
            """
            SELECT name, application_status, status
            FROM `tabMember`
            WHERE status = 'Active'
            AND application_status != 'Active'
            AND application_status IS NOT NULL
        """,
            as_dict=True,
        )

        fixed_count = 0
        for member in members_to_fix:
            # Update application_status to match status
            frappe.db.set_value("Member", member.name, "application_status", "Active")
            fixed_count += 1

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Fixed application_status for {fixed_count} members",
            "fixed_members": [m.name for m in members_to_fix],
        }

    except Exception as e:
        frappe.log_error(f"Error fixing member workflow status: {str(e)}", "Member Workflow Fix")
        return {"success": False, "message": f"Error: {str(e)}"}


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
