# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
TemplateCreationService - Membership dues schedule template management

This service handles creation of dues schedules from templates and creation
of default templates for membership types.

Extracted from membership_dues_schedule.py:
- create_from_template() - Lines 1913-2114 (203 LOC)
- create_default_template() - Lines 1878-1910 (35 LOC)

Architecture:
- StatelessService base class with unified logging and metrics
- Template-based instance creation with field copying
- Sophisticated dues rate priority logic
- Member document linking with concurrency handling

Business Logic:
- Template selection from explicit name, membership type, or auto-detection
- Field copying from template to individual schedules
- Dues rate priority: user-selected > CSV import > template defaults
- Default template creation with standard billing configuration

Dependencies:
- frappe.model.document for template and schedule management
- DocumentExistenceValidator for duplicate detection
- schedule_naming_helper for naming conventions
- Member document for linking schedules
"""

from typing import TYPE_CHECKING, Optional

import frappe
from frappe.utils import today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.validation_utilities import DocumentExistenceValidator

if TYPE_CHECKING:
    from frappe.model.document import Document


class TemplateCreationService(StatelessService):
    """
    Service for managing membership dues schedule templates.

    This service handles:
    - Creating individual schedules from templates
    - Creating default templates for membership types
    - Template field copying and configuration
    - Dues rate priority logic
    """

    def __init__(self):
        super().__init__(service_name="TemplateCreationService")

    def create_default_template(self, membership_type: str) -> "Document":
        """
        Create a default template for a membership type.

        Creates a basic template with standard billing configuration and links it
        back to the membership type document.

        Args:
            membership_type: Name of the membership type to create template for

        Returns:
            Created template document

        Raises:
            frappe.ValidationError: If template creation fails

        Template Configuration:
            - Billing Frequency: Annual
            - Contribution Mode: Calculator
            - Minimum Amount: 0
            - Suggested Amount: 15.0
            - Invoice Days Before: 30
            - Billing Day: 1
            - Auto Generate: Yes

        Example:
            >>> service = TemplateCreationService()
            >>> template = service.create_default_template("Standard")
            >>> print(template.schedule_name)  # "Default-Template-Standard"
        """
        try:
            membership_type_doc = frappe.get_doc("Membership Type", membership_type)

            # Create basic template
            template = frappe.new_doc("Membership Dues Schedule")
            template.is_template = 1
            template.schedule_name = f"Default-Template-{membership_type}"
            template.membership_type = membership_type
            template.status = "Active"
            template.billing_frequency = "Annual"
            template.contribution_mode = "Calculator"
            template.minimum_amount = 0
            template.suggested_amount = 15.0  # Default template value
            template.invoice_days_before = 30
            template.billing_day = 1  # Default template billing day
            template.auto_generate = 1

            template.insert()

            # Link back to membership type
            membership_type_doc.dues_schedule_template = template.name
            membership_type_doc.save()

            return template

        except Exception as e:
            self.logger.error(f"Error creating default template for {membership_type}: {str(e)}")
            raise frappe.ValidationError(f"Could not create default template for {membership_type}: {str(e)}")

    def create_from_template(
        self,
        member_name: str,
        template_name: Optional[str] = None,
        membership_type: Optional[str] = None,
        membership_name: Optional[str] = None,
        custom_amount: Optional[float] = None,
        custom_amount_reason: Optional[str] = None,
        custom_amount_approved: int = 0,
    ) -> str:
        """
        Create an individual dues schedule from a template.

        Creates a member-specific dues schedule by copying configuration from a
        template and applying member-specific customizations.

        Args:
            member_name: Name of the member to create schedule for
            template_name: Explicit template name to use (optional)
            membership_type: Membership type to get template from (optional)
            membership_name: Name of membership to link to (optional)
            custom_amount: Custom dues amount for CSV imports (optional)
            custom_amount_reason: Reason for custom amount (optional)
            custom_amount_approved: Whether custom amount is pre-approved (optional)

        Returns:
            Name of the created schedule document

        Raises:
            frappe.ValidationError: If template not found, not a template, or member
                has existing schedule

        Template Selection Logic:
            1. If template_name provided: use that template
            2. If membership_type provided: use dues_schedule_template from type
            3. Otherwise: auto-detect from member's active membership

        Dues Rate Priority:
            1. User-selected rate from application (highest priority)
            2. CSV import custom amount
            3. Template dues_rate or suggested_amount

        Example:
            >>> service = TemplateCreationService()
            >>> schedule_name = service.create_from_template(
            ...     member_name="Member-001",
            ...     membership_type="Standard"
            ... )
            >>> print(schedule_name)  # "Member-001-Standard-001"
        """

        # Determine template to use and get membership info
        membership_id = membership_name
        template = None

        if template_name:
            # Explicit template provided
            template = frappe.get_doc("Membership Dues Schedule", template_name)
            if not template.is_template:
                frappe.throw(f"{template_name} is not a template")

        elif membership_type:
            # Get template from membership type's explicit assignment
            membership_type_doc = frappe.get_doc("Membership Type", membership_type)

            if not membership_type_doc.dues_schedule_template:
                frappe.throw(
                    f"Membership Type '{membership_type}' has no dues schedule template assigned. "
                    f"Please assign a template to the membership type before creating schedules."
                )

            template = frappe.get_doc("Membership Dues Schedule", membership_type_doc.dues_schedule_template)
            if not template.is_template:
                frappe.throw(
                    f"Template '{membership_type_doc.dues_schedule_template}' is not marked as a template"
                )

        else:
            # Auto-detect from member's membership type (fallback)
            active_membership = frappe.db.get_value(
                "Membership",
                {"member": member_name, "status": "Active", "docstatus": 1},
                ["membership_type", "name"],
                as_dict=True,
            )
            if not active_membership:
                frappe.throw(f"Member {member_name} has no active membership")

            membership_type = active_membership.membership_type
            membership_id = active_membership.name

            # Get template from membership type's explicit assignment (NO implicit lookup)
            membership_type_doc = frappe.get_doc("Membership Type", membership_type)

            if not membership_type_doc.dues_schedule_template:
                frappe.throw(
                    f"Membership Type '{membership_type}' has no dues schedule template assigned. "
                    f"Cannot create dues schedule for member {member_name}. "
                    f"Please assign a template to the membership type first."
                )

            template = frappe.get_doc("Membership Dues Schedule", membership_type_doc.dues_schedule_template)
            if not template.is_template:
                frappe.throw(
                    f"Template '{membership_type_doc.dues_schedule_template}' is not marked as a template"
                )

        # Check if member already has a schedule
        existing = DocumentExistenceValidator.check_document_exists(
            "Membership Dues Schedule", {"member": member_name, "is_template": 0}
        )
        if existing:
            frappe.throw(f"Member {member_name} already has a dues schedule: {existing}")

        # Create new individual schedule
        schedule = frappe.new_doc("Membership Dues Schedule")

        # Copy template fields
        template_fields = [
            "membership_type",
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
        ]

        for field in template_fields:
            if hasattr(template, field) and getattr(template, field):
                setattr(schedule, field, getattr(template, field))

        # Set instance-specific fields
        schedule.is_template = 0
        schedule.member = member_name
        schedule.template_reference = template.name
        schedule.status = "Active"

        # SOPHISTICATED DUES RATE LOGIC: Preserve user's selected amount when available
        member_doc = frappe.get_doc("Member", member_name)
        user_selected_rate = getattr(member_doc, "dues_rate", None)

        # Check for CSV import custom fee stored on member record
        # This is the primary source for CSV imports (persisted to DB)
        member_csv_custom_fee = getattr(member_doc, "csv_import_custom_fee", None)
        member_csv_custom_fee_reason = getattr(member_doc, "csv_import_custom_fee_reason", None)

        # Use member's stored CSV fee if no custom_amount was passed as parameter
        if not custom_amount and member_csv_custom_fee:
            custom_amount = member_csv_custom_fee
            custom_amount_reason = member_csv_custom_fee_reason or "CSV import"
            self.logger.info(
                f"[DUES SCHEDULE] Using csv_import_custom_fee from member record: €{custom_amount} for {member_name}"
            )

        # Priority 1: User-selected rate from application (MOST AUTHORITATIVE)
        # User's explicit selection represents an active choice and should always win
        if user_selected_rate and user_selected_rate > 0:
            # User has selected a specific dues rate during application - preserve it
            schedule.dues_rate = user_selected_rate
            schedule.contribution_mode = "Custom"  # Mark as custom since user selected specific amount
            schedule.uses_custom_amount = 1
            schedule.custom_amount_reason = "Amount selected during membership application"

            # Validate user's selection against template minimum
            template_minimum = getattr(template, "minimum_amount", 0)
            if template_minimum and user_selected_rate < template_minimum:
                frappe.throw(
                    f"Selected contribution amount (€{user_selected_rate:.2f}) is less than the minimum required "
                    f"for {template.membership_type} membership (€{template_minimum:.2f}). "
                    f"Please contact support to resolve this discrepancy."
                )
        # Priority 2: CSV import custom amount (from parameter or member record)
        # Historic data from imports, should not override active user choices
        elif custom_amount and custom_amount > 0:
            schedule.dues_rate = custom_amount
            schedule.contribution_mode = "Custom"
            schedule.uses_custom_amount = 1
            schedule.custom_amount_reason = custom_amount_reason or "Imported from CSV"
            schedule.custom_amount_approved = custom_amount_approved
            self.logger.info(
                f"[DUES SCHEDULE] Using CSV import custom amount: €{custom_amount:.2f} for member {member_name}"
            )
        # Priority 3: Template fallbacks
        else:
            # No user selection - use template's dues_rate as fallback
            template_dues_rate = getattr(template, "dues_rate", None)
            if template_dues_rate and template_dues_rate > 0:
                schedule.dues_rate = template_dues_rate
            else:
                # Final fallback to suggested_amount if template has no dues_rate
                schedule.dues_rate = getattr(template, "suggested_amount", 0)

        # CRITICAL: Set the membership field if available
        if membership_id:
            schedule.membership = membership_id

        # Use new naming pattern with sequence numbers
        from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name

        schedule.schedule_name = generate_dues_schedule_name(member_name, template.membership_type)

        # Set member-specific data
        member = frappe.get_doc("Member", member_name)
        schedule.member_name = member.full_name

        # Set initial billing date based on member anniversary and frequency
        next_billing = schedule.calculate_next_invoice_date()
        if next_billing:
            schedule.next_invoice_date = next_billing
        else:
            schedule.next_invoice_date = today()

        # Insert and return
        schedule.insert()

        # Link back to member with concurrency handling
        member.current_dues_schedule = schedule.name
        member.dues_rate = schedule.dues_rate

        # Check if we're in a bulk operation and mark the member document accordingly
        # This flag will persist through the save() call and prevent fee override validation
        bulk_flag = getattr(frappe.flags, "bulk_member_operations", False)
        if bulk_flag:
            member._system_update = True

        try:
            member.save()
        except frappe.TimestampMismatchError:
            # Reload member and retry save once
            member.reload()
            member.current_dues_schedule = schedule.name
            member.dues_rate = schedule.dues_rate
            member.save()

        return schedule.name


def get_template_creation_service() -> TemplateCreationService:
    """Get singleton instance of TemplateCreationService"""
    return TemplateCreationService()
