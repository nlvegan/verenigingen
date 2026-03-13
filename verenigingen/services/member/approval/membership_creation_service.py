"""
Membership Creation Service - Handles membership creation during member application approval.

This service extracts the complex 226-line create_membership_on_approval() method from
Member DocType into focused, testable methods.

Key Responsibilities:
    - Validate membership creation parameters
    - Handle CSV import custom fee logic
    - Create or reuse membership records
    - Ensure dues schedules exist
    - Generate membership invoices
    - Consolidate member field updates
    - Handle rollback on failures

Architecture:
    - StatelessService base class with unified logging and metrics
    - Each method handles ONE specific responsibility
    - Clear input/output contracts
    - Comprehensive error handling
    - Maintains rollback/retry logic from original implementation

ERROR HANDLING PATTERN: Exception-Based Pattern
===============================================
All methods raise exceptions on errors: frappe.ValidationError, frappe.PermissionError

Rationale: Internal business logic service called only from Member.create_membership_on_approval().
Exception pattern provides:
- Automatic transaction rollback on errors
- Frappe UI error display integration
- Transactional behavior (all-or-nothing)
- Cleaner code without constant result checking

See: docs/patterns/ERROR_HANDLING_PATTERNS.md
"""

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.service_error_handler import create_service_result, handle_service_error


class MembershipCreationService(StatelessService):
    """Service for creating memberships during member approval workflow"""

    def __init__(self):
        super().__init__(service_name="MembershipCreationService")

    def _validate_membership_creation_inputs(
        self,
        member_doc,
        start_date=None,
        custom_dues_rate=None,
        approval_fields=None,
        is_csv_import=False,
    ):
        """
        Validate all inputs for membership creation.

        Provides comprehensive input validation at service layer for defense-in-depth.

        Args:
            member_doc: Member document instance
            start_date: Custom start date for membership (optional)
            custom_dues_rate: Custom dues rate for CSV imports (optional)
            approval_fields: Dict of approval fields to set (optional)

        Raises:
            frappe.ValidationError: If any validation fails
        """
        # Validate member_doc is a valid document
        if not member_doc:
            frappe.throw(_("Member document is required"))

        if not hasattr(member_doc, "doctype") or member_doc.doctype != "Member":
            frappe.throw(_("Invalid member document provided"))

        if not member_doc.name:
            frappe.throw(_("Member document must be saved before creating membership"))

        # Validate start_date if provided (skip for imports — historic dates are expected)
        if start_date and not is_csv_import:
            from verenigingen.utils.validation_utilities import validate_historical_date_window

            validate_historical_date_window(
                start_date,
                max_years_past=5,
                max_days_future=30,
                field_name="start_date",
                throw_on_error=True,
            )

        # Validate custom_dues_rate if provided
        if custom_dues_rate is not None:
            try:
                rate = float(custom_dues_rate)
                if rate < 0:
                    frappe.throw(
                        _("Custom dues rate must be non-negative. Provided: {0}").format(custom_dues_rate)
                    )
                if rate > 10000:  # Sanity check for reasonable dues amount
                    frappe.throw(
                        _("Custom dues rate seems unreasonably high: {0}. Please verify.").format(
                            custom_dues_rate
                        )
                    )
            except (TypeError, ValueError):
                frappe.throw(
                    _("Custom dues rate must be a valid number. Provided: {0}").format(custom_dues_rate)
                )

        # Validate approval_fields if provided
        if approval_fields is not None and not isinstance(approval_fields, dict):
            frappe.throw(
                _("Approval fields must be a dictionary. Provided type: {0}").format(
                    type(approval_fields).__name__
                )
            )

    def create_membership_on_approval(
        self,
        member_doc,
        start_date=None,
        create_invoice=True,
        custom_dues_rate=None,
        custom_rate_reason=None,
        is_csv_import=False,
        approval_fields=None,
    ):
        """
        Create membership record when application is approved.

        This is the main orchestration method that coordinates all membership creation steps.

        Args:
            member_doc: Member document instance
            start_date: Custom start date for membership (defaults to today)
            create_invoice: Whether to create invoice (False for historic CSV imports)
            custom_dues_rate: Custom dues rate for CSV imports
            custom_rate_reason: Reason for custom dues rate
            is_csv_import: Flag indicating CSV import with historic date
            approval_fields: Dict of approval fields to set

        Returns:
            Membership: Created or reused membership document

        Raises:
            frappe.ValidationError: If validation fails
            Exception: For other errors during creation
        """
        try:
            self.logger.info(
                f"MembershipCreationService: Starting for {member_doc.name}, "
                f"start_date={start_date}, create_invoice={create_invoice}, "
                f"custom_dues_rate={custom_dues_rate}"
            )

            # Step 0: Validate all inputs (defense-in-depth)
            self._validate_membership_creation_inputs(
                member_doc, start_date, custom_dues_rate, approval_fields, is_csv_import
            )

            # Step 1: Validate membership creation parameters
            membership_type = self._validate_and_get_membership_type(member_doc)

            # Step 2: Handle CSV import custom fee (if applicable)
            if custom_dues_rate:
                self._set_csv_import_custom_fee(member_doc, custom_dues_rate, custom_rate_reason)

            # Step 3: Get existing membership or create new one
            membership = self._get_or_create_membership(
                member_doc, membership_type, start_date, is_csv_import
            )

            # Step 4: Ensure dues schedule exists
            self._ensure_dues_schedule_exists(member_doc, membership, membership_type)

            # Step 5: Generate invoice (if needed)
            invoice = None
            if create_invoice:
                invoice = self._create_membership_invoice(member_doc, membership, membership_type)

            # Step 6: Consolidate all member field updates
            dues_schedule = self._consolidate_member_updates(member_doc, membership, invoice, approval_fields)

            # Step 7: Save member with rollback on failure
            self._save_member_with_rollback(member_doc, membership, dues_schedule, invoice, approval_fields)

            self.logger.info(
                f"MembershipCreationService: Successfully created membership for {member_doc.name}"
            )
            return membership

        except Exception as e:
            self.logger.error(f"MembershipCreationService: Error for {member_doc.name}: {str(e)}")
            frappe.throw(_("Error creating membership: {0}").format(str(e)))

    def _validate_and_get_membership_type(self, member_doc):
        """
        Validate that member has a selected membership type with a valid dues schedule template.

        Args:
            member_doc: Member document instance

        Returns:
            Document: Membership Type document

        Raises:
            frappe.ValidationError: If no membership type selected or no template configured
        """
        if not member_doc.selected_membership_type:
            frappe.throw(_("No membership type selected for this application"))

        membership_type = frappe.get_doc("Membership Type", member_doc.selected_membership_type)

        # Validate that a dues schedule template is available.
        # Either the membership type has one configured, or the member already has
        # one resolved (e.g. from CSV import via Verenigingen Settings payment period mapping).
        has_application_template = getattr(member_doc, "application_dues_schedule", None)
        if not membership_type.dues_schedule_template and not has_application_template:
            frappe.throw(
                _(
                    "Membership Type '{0}' has no dues schedule template configured. "
                    "Please assign a template to this membership type before approving applications."
                ).format(membership_type.name)
            )

        # Validate that the membership type's template exists (if it has one)
        if membership_type.dues_schedule_template and not frappe.db.exists(
            "Membership Dues Schedule", membership_type.dues_schedule_template
        ):
            frappe.throw(
                _(
                    "Dues schedule template '{0}' configured for membership type '{1}' does not exist. "
                    "Please fix the membership type configuration."
                ).format(membership_type.dues_schedule_template, membership_type.name)
            )

        return membership_type

    def _set_csv_import_custom_fee(self, member_doc, custom_dues_rate, custom_rate_reason):
        """
        Set custom dues rate for CSV imports.

        Sets fields on document object for consolidated save later.

        Args:
            member_doc: Member document instance
            custom_dues_rate: Custom fee amount
            custom_rate_reason: Reason for custom fee
        """
        # Set fields on document object (not database)
        # These will be saved in the consolidated save at the end
        member_doc.csv_import_custom_fee = custom_dues_rate
        member_doc.csv_import_custom_fee_reason = custom_rate_reason or "Imported from CSV"

        self.logger.info(
            f"MembershipCreationService: Set CSV import custom fee {custom_dues_rate} for {member_doc.name}"
        )

    def _get_or_create_membership(self, member_doc, membership_type, start_date, is_csv_import):
        """
        Get existing active membership or create new one.

        Handles retry scenarios where membership was created but approval failed.

        Args:
            member_doc: Member document instance
            membership_type: Membership Type document
            start_date: Membership start date (None = today)
            is_csv_import: Whether this is CSV import

        Returns:
            Document: Membership document (existing or newly created)

        Raises:
            frappe.ValidationError: If existing membership has wrong type/date
        """
        # Check for existing active membership
        existing_membership = frappe.db.get_value(
            "Membership",
            {"member": member_doc.name, "status": "Active", "docstatus": 1},
            ["name", "membership_type", "start_date"],
            as_dict=True,
        )

        if existing_membership:
            return self._handle_existing_membership(member_doc, existing_membership, membership_type)

        # No existing membership - create new one
        return self._create_new_membership(member_doc, membership_type, start_date, is_csv_import)

    def _handle_existing_membership(self, member_doc, existing_membership, membership_type):
        """
        Handle existing membership in retry scenario.

        Args:
            member_doc: Member document instance
            existing_membership: Dict with existing membership data
            membership_type: Membership Type document

        Returns:
            Document: Existing membership if valid for reuse

        Raises:
            frappe.ValidationError: If existing membership cannot be reused
        """
        days_old = date_diff(today(), existing_membership.start_date)
        same_type = existing_membership.membership_type == membership_type.name

        if same_type and days_old <= 1:
            # Existing membership is appropriate - reuse it
            self.logger.info(
                f"MembershipCreationService: Reusing membership {existing_membership.name} "
                f"for {member_doc.name} (retry scenario)"
            )
            return frappe.get_doc("Membership", existing_membership.name)

        # Existing membership is wrong type or too old
        frappe.throw(
            _(
                "Member already has an active membership ({0}) with type '{1}' from {2}. "
                "Please cancel the existing membership before approving with a different type."
            ).format(
                existing_membership.name,
                existing_membership.membership_type,
                frappe.utils.format_date(existing_membership.start_date),
            )
        )

    def _create_new_membership(self, member_doc, membership_type, start_date, is_csv_import):
        """
        Create new membership record.

        Args:
            member_doc: Member document instance
            membership_type: Membership Type document
            start_date: Membership start date (None = today)
            is_csv_import: Whether this is CSV import

        Returns:
            Document: Newly created and submitted membership
        """
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member_doc.name,
                "membership_type": membership_type.name,
                "start_date": start_date or today(),
                "status": "Active",
            }
        )

        # Set CSV import flag for proper renewal_date calculation
        if is_csv_import:
            membership._is_csv_import = True

        # Skip the on_submit hook's dues schedule creation — the service layer
        # handles it in _ensure_dues_schedule_exists with proper template resolution
        # (application_dues_schedule, payment_period, etc.).
        membership.flags.skip_dues_schedule_creation = True

        # Use context manager to skip member updates in membership.on_submit()
        # We'll consolidate all updates into one save later for performance
        from verenigingen.utils.document_coordination import skip_child_document_updates

        with skip_child_document_updates(
            member_doc, "Membership", "Consolidating member updates for approval"
        ):
            membership.insert()
            membership.submit()

        self.logger.info(
            f"MembershipCreationService: Created membership {membership.name} for {member_doc.name}"
        )
        return membership

    def _resolve_dues_template(self, member_doc, membership_type):
        """Resolve which dues schedule template to use for a new member.

        Checks the applicant's selected template (application_dues_schedule) and
        validates it before use. Falls back to the membership type's default template.

        Args:
            member_doc: Member document instance
            membership_type: Membership Type document

        Returns:
            str or None: Template name if applicant selected a valid one, else None (use default)
        """
        selected = getattr(member_doc, "application_dues_schedule", None)
        if not selected:
            return None

        if not frappe.db.exists("Membership Dues Schedule", selected):
            self.logger.warning(
                f"MembershipCreationService: application_dues_schedule '{selected}' "
                f"does not exist, falling back to default"
            )
            return None

        template_fields = frappe.db.get_value(
            "Membership Dues Schedule",
            selected,
            ["is_template", "membership_type"],
            as_dict=True,
        )

        if not template_fields.get("is_template"):
            self.logger.warning(
                f"MembershipCreationService: '{selected}' is not a template, falling back to default"
            )
            return None

        if (
            template_fields.get("membership_type")
            and template_fields["membership_type"] != membership_type.name
        ):
            self.logger.warning(
                f"MembershipCreationService: template '{selected}' belongs to "
                f"'{template_fields['membership_type']}', not '{membership_type.name}', "
                f"falling back to default"
            )
            return None

        self.logger.info(
            f"MembershipCreationService: Using applicant-selected template '{selected}' "
            f"for {member_doc.name}"
        )
        return selected

    def _update_schedule_from_template(self, schedule_name, template_name):
        """Update an existing schedule to match a different template.

        Called when the membership on_submit hook auto-created a schedule using the
        default template, but the applicant selected a different one.

        Args:
            schedule_name: Name of the existing schedule to update
            template_name: Name of the template to copy fields from
        """
        template = frappe.get_doc("Membership Dues Schedule", template_name)
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

        copy_fields = [
            "billing_frequency",
            "custom_frequency_number",
            "custom_frequency_unit",
            "contribution_mode",
            "base_multiplier",
            "minimum_amount",
            "suggested_amount",
            "invoice_days_before",
            "billing_day",
            "payment_terms_template",
            "auto_generate",
            "dues_rate",
        ]
        for field in copy_fields:
            value = getattr(template, field, None)
            if value is not None and value != "":
                setattr(schedule, field, value)

        schedule.template_reference = template_name
        schedule.save()
        self.logger.info(
            f"MembershipCreationService: Updated schedule {schedule_name} " f"from template '{template_name}'"
        )

    def _ensure_dues_schedule_exists(self, member_doc, membership, membership_type):
        """
        Ensure membership dues schedule exists.

        Creates schedule if it doesn't exist. This was previously done in
        membership.on_submit() hook, but that doesn't run for reused memberships.

        Args:
            member_doc: Member document instance
            membership: Membership document
            membership_type: Membership Type document
        """
        existing_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_doc.name, "is_template": 0}, "name"
        )

        if existing_schedule:
            # Check if applicant selected a different template than what was auto-created
            template_name = self._resolve_dues_template(member_doc, membership_type)
            if template_name:
                current_ref = frappe.db.get_value(
                    "Membership Dues Schedule", existing_schedule, "template_reference"
                )
                if current_ref != template_name:
                    self._update_schedule_from_template(existing_schedule, template_name)
            self.logger.info(
                f"MembershipCreationService: Dues schedule {existing_schedule} "
                f"already exists for {member_doc.name}"
            )
            return

        # Create dues schedule
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
            MembershipDuesSchedule,
        )

        # Get custom fee from various sources:
        # 1. CSV import custom fee (set by _set_csv_import_custom_fee)
        # 2. Application custom amount (set via dues_rate from custom_contribution_fee)
        csv_custom_fee = getattr(member_doc, "csv_import_custom_fee", None)
        csv_custom_fee_reason = getattr(member_doc, "csv_import_custom_fee_reason", None)

        # Fallback to dues_rate if no CSV custom fee (from application custom amount)
        custom_amount = csv_custom_fee
        custom_amount_reason = csv_custom_fee_reason
        if not custom_amount and getattr(member_doc, "dues_rate", None):
            custom_amount = member_doc.dues_rate
            custom_amount_reason = getattr(member_doc, "fee_override_reason", None)

        # Use applicant's selected template if valid, otherwise fall back to membership type default
        template_name = self._resolve_dues_template(member_doc, membership_type)

        try:
            schedule_name = MembershipDuesSchedule.create_from_template(
                member_doc.name,
                template_name=template_name,
                membership_type=membership_type.name,
                membership_name=membership.name,
                custom_amount=custom_amount,
                custom_amount_reason=custom_amount_reason,
            )
            self.logger.info(
                f"MembershipCreationService: Created dues schedule {schedule_name} for {member_doc.name}"
                + (f" with custom amount €{custom_amount}" if custom_amount else "")
            )
        except Exception as e:
            self.logger.error(f"MembershipCreationService: Failed to create dues schedule: {str(e)}")
            frappe.log_error(
                frappe.get_traceback(),
                f"Dues Schedule Creation Failed: {member_doc.name}",
            )
            # Don't fail approval if dues schedule creation fails
            frappe.msgprint(
                _("Warning: Dues schedule creation failed: {0}").format(str(e)[:200]),
                alert=True,
                indicator="orange",
            )

    def _create_membership_invoice(self, member_doc, membership, membership_type):
        """
        Create membership invoice.

        Args:
            member_doc: Member document instance
            membership: Membership document
            membership_type: Membership Type document

        Returns:
            Document: Sales Invoice document or None if creation fails
        """
        from verenigingen.utils.application_payments import create_membership_invoice

        try:
            current_fee = member_doc.get_current_membership_fee()
            invoice = create_membership_invoice(
                member_doc, membership, membership_type, current_fee["amount"]
            )
            self.logger.info(
                f"MembershipCreationService: Created invoice {invoice.name} for {member_doc.name}"
            )
            return invoice
        except Exception as e:
            self.logger.error(f"MembershipCreationService: Failed to create invoice: {str(e)}")
            frappe.msgprint(
                _("Warning: Invoice creation failed: {0}").format(str(e)), alert=True, indicator="orange"
            )
            return None

    def _consolidate_member_updates(self, member_doc, membership, invoice, approval_fields):
        """
        Consolidate all member field updates after membership creation.

        Reloads member to get latest data, then sets all fields for single save.

        Args:
            member_doc: Member document instance
            membership: Membership document
            invoice: Sales Invoice document or None
            approval_fields: Dict of approval fields to set

        Returns:
            str: Dues schedule name or None
        """
        self.logger.info(
            f"MembershipCreationService: Reloading member {member_doc.name} for consolidated updates"
        )
        member_doc.reload()

        # Set current membership plan
        member_doc.current_membership_plan = membership.name

        # Set current dues schedule
        dues_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_doc.name, "is_template": 0}, "name"
        )
        if dues_schedule:
            member_doc.current_dues_schedule = dues_schedule

        # Update membership duration fields
        from verenigingen.services.member.utils.membership_duration_service import (
            update_member_duration_fields,
        )

        update_member_duration_fields(member_doc)

        # Set invoice fields if invoice was created
        if invoice:
            member_doc.application_invoice = invoice.name
            member_doc.application_payment_status = "Pending"

        # Set approval fields if provided
        if approval_fields:
            for field, value in approval_fields.items():
                setattr(member_doc, field, value)

        return dues_schedule

    def _save_member_with_rollback(self, member_doc, membership, dues_schedule, invoice, approval_fields):
        """
        Save member with retry logic and rollback on failure.

        Uses save_with_rollback utility to cancel membership if member save fails.

        SECURITY PATTERN: _system_update Flag Usage
        ============================================
        This method uses `member_doc._system_update = True` to bypass the fee override
        business rule validation. This is an APPROVED pattern for system-initiated workflows.

        Why This Is Appropriate:
        - Context: System-initiated approval workflow (not user-initiated change)
        - Permissions: Already validated when admin approved application
        - Bypass Type: Business rule only (fee override check), NOT permission validation
        - Compensation: Comprehensive SECURITY_AUDIT logging captures who/when/why/context
        - Rollback: save_with_rollback provides atomicity with membership cancellation

        Why secure_document_operation Is NOT Used:
        - secure_document_operation validates permissions (already done at API layer)
        - save_with_rollback provides rollback coordination (not in secure_document_operation)
        - Combining both would require architectural changes affecting all callers
        - Current pattern: Permission validation at API → Business logic uses rollback coordination

        Alternative Considered: Modify Member.validate() to check workflow context
        - Would require passing context through entire call chain
        - Would complicate Member DocType with approval-specific logic
        - Current approach isolates workflow logic to service layer

        See: docs/patterns/SYSTEM_UPDATE_PATTERN.md for guidelines

        Args:
            member_doc: Member document instance
            membership: Membership document to rollback if save fails
            dues_schedule: Dues schedule name
            invoice: Invoice document or None
            approval_fields: Approval fields dict
        """
        # Mark as system update to bypass fee override validation during approval workflow
        # This is a business rule bypass, not a permission bypass
        member_doc._system_update = True

        # SECURITY_AUDIT: Comprehensive logging compensates for business rule bypass
        if member_doc.dues_rate:
            self.logger.warning(
                f"SECURITY_AUDIT: Fee override validation bypassed via _system_update "
                f"for member {member_doc.name}, dues_rate={member_doc.dues_rate}, "
                f"user={frappe.session.user}, context=MembershipCreationService.approval_workflow"
            )

        # Define field restoration callback for retry logic
        def restore_member_fields(doc):
            """Restore all member fields after reload during retry"""
            doc.current_membership_plan = membership.name
            if dues_schedule:
                doc.current_dues_schedule = dues_schedule

            # Re-apply duration fields after reload
            from verenigingen.services.member.utils.membership_duration_service import (
                update_member_duration_fields,
            )

            update_member_duration_fields(doc)

            if invoice:
                doc.application_invoice = invoice.name
                doc.application_payment_status = "Pending"

            # Restore approval fields
            if approval_fields:
                for field, value in approval_fields.items():
                    setattr(doc, field, value)

            doc._system_update = True

            # Security audit log
            if doc.dues_rate:
                self.logger.warning(
                    f"SECURITY_AUDIT: Fee override validation bypassed via _system_update "
                    f"for member {doc.name}, dues_rate={doc.dues_rate}, "
                    f"user={frappe.session.user}, context=MembershipCreationService (retry)"
                )

        # Use retry utility with automatic rollback of membership if member save fails
        from verenigingen.utils.document_save_retry import save_with_rollback

        self.logger.info(
            f"MembershipCreationService: Saving member {member_doc.name} with rollback protection"
        )
        save_with_rollback(
            member_doc,
            rollback_docs=[membership],  # Cancel membership if member save fails
            max_retries=1,
            field_restore_callback=restore_member_fields,
        )


def get_membership_creation_service() -> MembershipCreationService:
    """Get instance of MembershipCreationService."""
    return MembershipCreationService()
