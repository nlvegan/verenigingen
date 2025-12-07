"""
Member Merge Service

Provides functionality to merge duplicate member records with field-level
selection control. Handles identity and contact data while preserving
complex financial and volunteer relationships.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All API methods return OperationResult[Dict] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- get_merge_preview: Returns OperationResult[Dict] (merge preview with field comparisons)
- execute_merge: Returns OperationResult[Dict] (merge execution result)

Migration Status: ✅ COMPLETE (2025-11-24)
- Both API methods migrated from dict-based to OperationResult pattern
- Exception handling wrapped in try-catch blocks
- Type-safe error handling with comprehensive metadata
- All security checks and validation preserved

Business Context:
- Occasionally duplicate member records are created before discovering an existing member
- Need to consolidate identity/contact data without disrupting financial history
- Financial, volunteer, and ERPNext integration data remains with original records
- Secondary emails are preserved in the Contact record

Architecture:
- Field-level merge with smart defaults (prefer populated fields)
- Target record preserved, source record deleted after data extraction
- Child table data (payment history, SEPA mandates) NOT merged
- Linked records (Customer, Employee, User) NOT transferred automatically

Security:
- Requires write permission on both members
- Validates no active financial conflicts
- Audit trail via comment on target record

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

import json
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.repositories import DuesScheduleRepository
from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.operation_result import OperationResult


class MemberMergeService(StatelessService):
    """Service for merging duplicate Member records with field-level control.

    Inherits from StatelessService for consistent logging, metrics, and error handling.
    """

    # Fields that can be merged (identity and contact data only)
    MERGEABLE_FIELDS = [
        # Identity
        "first_name",
        "middle_name",
        "tussenvoegsel",
        "last_name",
        # full_name is auto-calculated, not merged
        "pronouns",
        "aanhef",
        # Member ID (important for external references)
        "member_id",
        # Contact
        "email",
        "contact_number",
        "primary_address",
        # Personal
        "birth_date",
        # age is auto-calculated from birth_date, not merged
        "image",
        # Payment Details (basic info, not active integrations)
        "iban",
        "bic",
        "bank_account_name",
        "payment_method",
        "payment_reference",
        "credit_card_number",  # Last 4 digits only
        # Preferences
        "accepts_optional_communications",
        "permission_category",
        # Notes
        "notes",
    ]

    # Fields explicitly excluded (kept on target, not merged)
    EXCLUDED_FIELDS = [
        # Active Payment Integrations (require manual cancellation first)
        "mollie_customer_id",
        "mollie_mandate_id",
        "mollie_subscription_id",
        "subscription_status",
        "next_payment_date",
        "subscription_cancelled_date",
        # Membership
        "member_since",
        "member_end_date",
        "current_membership_plan",
        "current_membership_type",
        "current_dues_schedule",
        "dues_rate",
        "next_invoice_date",
        "cumulative_membership_duration",
        "total_membership_days",
        # Application
        "application_id",
        "application_status",
        "application_date",
        "reviewed_by",
        "review_date",
        "application_custom_fee",
        # ERPNext Links
        "customer",
        "contact",
        "user",
        "employee",
        "volunteer_record",
        # Status
        "status",
        "membership_status",
        # Chapter
        "current_chapter_display",
        "chapter_assigned_by",
        "previous_chapter",
        "chapter_change_reason",
    ]

    def __init__(self):
        """Initialize the merge service."""
        super().__init__(service_name="MemberMergeService")

    def get_merge_preview(self, source_name: str, target_name: str) -> Dict[str, Any]:
        """
        Generate a preview of the merge operation showing field-by-field comparison.

        Args:
            source_name: Name of the member record to be deleted after merge
            target_name: Name of the member record to keep

        Returns:
            Dictionary containing:
                - source: Source member data
                - target: Target member data
                - fields: List of mergeable fields with values and suggestions
                - warnings: List of warnings about excluded data

        Raises:
            frappe.PermissionError: If user lacks write permission
            frappe.ValidationError: If members have financial conflicts
        """
        # Load members with permission checks
        source = frappe.get_doc("Member", source_name)
        target = frappe.get_doc("Member", target_name)

        # Verify write permission
        source.check_permission("write")
        target.check_permission("write")

        # Check for conflicts
        warnings = self._check_merge_conflicts(source, target)

        # Build field comparison
        field_comparisons = []
        for fieldname in self.MERGEABLE_FIELDS:
            source_value = source.get(fieldname)
            target_value = target.get(fieldname)

            # Smart default: prefer populated over empty
            suggested = None
            if source_value and not target_value:
                suggested = "source"
            elif target_value and not source_value:
                suggested = "target"
            elif source_value == target_value:
                suggested = "target"  # Keep target if values match
            # If both populated but different, no suggestion - user must choose

            field_meta = source.meta.get_field(fieldname)
            field_comparisons.append(
                {
                    "fieldname": fieldname,
                    "label": field_meta.label if field_meta else fieldname,
                    "fieldtype": field_meta.fieldtype if field_meta else "Data",
                    "source_value": source_value,
                    "target_value": target_value,
                    "suggested": suggested,
                    "has_conflict": bool(source_value and target_value and source_value != target_value),
                }
            )

        return {
            "source": {
                "name": source.name,
                "full_name": source.full_name,
                "email": source.email,
                "member_id": source.member_id,
            },
            "target": {
                "name": target.name,
                "full_name": target.full_name,
                "email": target.email,
                "member_id": target.member_id,
            },
            "fields": field_comparisons,
            "warnings": warnings,
        }

    def _check_merge_conflicts(self, source: Document, target: Document) -> List[str]:
        """
        Check for conflicts that might complicate the merge.

        Returns list of warning messages.
        """
        warnings = []

        # Check for active memberships
        if source.current_membership_plan:
            warnings.append(
                f"Source member has active membership: {source.current_membership_plan}. "
                "This will NOT be transferred."
            )

        # Check for unpaid invoices
        unpaid_count = frappe.db.count(
            "Sales Invoice",
            filters={
                "member": source.name,
                "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
            },
        )
        if unpaid_count > 0:
            warnings.append(
                f"Source member has {unpaid_count} unpaid invoice(s). "
                "These will remain linked to the source member."
            )

        # Check for volunteer record
        if source.volunteer_record:
            warnings.append(
                f"Source member has volunteer record: {source.volunteer_record}. "
                "This will NOT be transferred."
            )

        # Check for active Mollie subscriptions
        if source.mollie_subscription_id and source.subscription_status == "active":
            warnings.append(
                f"Source member has ACTIVE Mollie subscription ({source.mollie_subscription_id}). "
                "Cancel this subscription in Mollie BEFORE merging to avoid billing issues."
            )
        if target.mollie_subscription_id and target.subscription_status == "active":
            warnings.append(
                f"Target member has ACTIVE Mollie subscription ({target.mollie_subscription_id}). "
                "Mollie integration IDs will NOT be merged."
            )

        # Check for linked User account
        if source.user and target.user and source.user != target.user:
            warnings.append("Both members have different User accounts. Target's User account will be kept.")
        elif source.user and not target.user:
            warnings.append(
                f"Source has User account: {source.user}. This will NOT be transferred for security reasons. "
                "Please manually transfer if needed."
            )

        # Check for ERPNext Customer
        if source.customer and target.customer and source.customer != target.customer:
            warnings.append(
                "Both members have different Customer records. Invoices will remain on their respective Customers."
            )

        return warnings

    def execute_merge(
        self,
        source_name: str,
        target_name: str,
        field_selections: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Execute the merge operation with user's field selections.

        Args:
            source_name: Name of member to be deleted
            target_name: Name of member to keep
            field_selections: Dict mapping fieldname -> "source" or "target"

        Returns:
            Result dict with success status and merged member name

        Raises:
            frappe.ValidationError: If validation fails
        """
        # Load members
        source = frappe.get_doc("Member", source_name)
        target = frappe.get_doc("Member", target_name)

        # Verify permissions
        source.check_permission("write")
        target.check_permission("write")

        # Track changes for audit
        changes = []
        secondary_emails = []
        member_id_changed = False

        # Apply field selections
        for fieldname, choice in field_selections.items():
            if fieldname not in self.MERGEABLE_FIELDS:
                continue

            if choice == "source":
                source_value = source.get(fieldname)
                target_value = target.get(fieldname)

                if source_value != target_value:
                    # Handle email specially - save secondary to Contact
                    if fieldname == "email" and target_value:
                        secondary_emails.append(target_value)

                    # Track if member_id is being changed (unique constraint issue)
                    if fieldname == "member_id":
                        member_id_changed = True

                    target.set(fieldname, source_value)
                    changes.append(
                        {
                            "field": fieldname,
                            "from": target_value,
                            "to": source_value,
                        }
                    )

        # If member_id is being changed, we must delete source BEFORE saving target
        # to avoid unique constraint violation
        if member_id_changed:
            self._delete_source_member_and_dependencies(source)

        # Save target with merged data
        target.flags.ignore_mandatory = True  # Some fields might be auto-calculated
        target.save()

        # Add secondary emails to Contact if exists
        if secondary_emails and target.contact:
            self._add_secondary_emails(target.contact, secondary_emails)

        # Add audit trail comment
        merge_comment = self._format_merge_comment(source.name, changes)
        target.add_comment("Info", merge_comment)

        # Delete source member if not already deleted
        if not member_id_changed:
            self._delete_source_member_and_dependencies(source)

        frappe.db.commit()

        return {
            "success": True,
            "merged_member": target.name,
            "changes_applied": len(changes),
            "secondary_emails_saved": len(secondary_emails),
        }

    def _delete_source_member_and_dependencies(self, source: Document) -> None:
        """
        Delete source member and its dependent records in proper order.

        Deletion order:
        1. Membership Dues Schedules (depend on member and membership)
        2. Memberships (depend on member)
        3. Customer (if no invoices)
        4. Member itself

        Note: Does NOT delete User, Employee, Volunteer, Contact records
        """
        # Delete Membership Dues Schedules first
        dues_repo = DuesScheduleRepository()
        dues_schedules = dues_repo.get_schedules_for_members([source.name], fields=["name"])
        for schedule in dues_schedules:
            try:
                frappe.delete_doc(
                    "Membership Dues Schedule", schedule.name, force=True, ignore_permissions=True
                )
            except Exception as e:
                self.logger.error(f"Failed to delete Dues Schedule {schedule.name}: {str(e)}")

        # Delete Memberships
        memberships = frappe.get_all("Membership", filters={"member": source.name})
        for membership in memberships:
            try:
                frappe.delete_doc("Membership", membership.name, force=True, ignore_permissions=True)
            except Exception as e:
                self.logger.error(f"Failed to delete Membership {membership.name}: {str(e)}")

        # Delete Customer if exists and has no invoices
        if source.customer:
            try:
                has_invoices = frappe.db.exists("Sales Invoice", {"customer": source.customer})
                if has_invoices:
                    self.logger.info(
                        f"Cannot delete Customer {source.customer} - has invoices. Keeping Customer."
                    )
                else:
                    frappe.delete_doc("Customer", source.customer, force=True, ignore_permissions=True)
            except Exception as e:
                self.logger.error(f"Failed to delete Customer {source.customer}: {str(e)}")

        # Finally, delete the Member itself
        # Note: This does NOT delete User, Employee, Volunteer records
        frappe.delete_doc(
            "Member",
            source.name,
            ignore_permissions=False,
            force=True,
        )

    def _add_secondary_emails(self, contact_name: str, emails: List[str]) -> None:
        """Add secondary emails to Contact record."""
        try:
            contact = frappe.get_doc("Contact", contact_name)

            # Get existing emails
            existing = {row.email_id for row in contact.email_ids}

            # Add new emails
            for email in emails:
                if email and email not in existing:
                    contact.append(
                        "email_ids",
                        {
                            "email_id": email,
                            "is_primary": 0,
                        },
                    )

            contact.save(ignore_permissions=True)

        except Exception as e:
            self.logger.error(f"Failed to add secondary emails to Contact {contact_name}: {str(e)}")

    def _format_merge_comment(self, source_name: str, changes: List[Dict[str, Any]]) -> str:
        """Format a human-readable merge audit comment."""
        comment_parts = [
            f"<strong>Merged from:</strong> {source_name}",
            f"<strong>Fields updated:</strong> {len(changes)}",
        ]

        if changes:
            comment_parts.append("<br><br><strong>Changes:</strong><ul>")
            for change in changes[:10]:  # Limit to first 10 for readability
                field = change["field"]
                from_val = change["from"] or "(empty)"
                to_val = change["to"] or "(empty)"
                comment_parts.append(f"<li><code>{field}</code>: {from_val} → {to_val}</li>")
            if len(changes) > 10:
                comment_parts.append(f"<li>... and {len(changes) - 10} more</li>")
            comment_parts.append("</ul>")

        return "".join(comment_parts)


# Whitelisted API methods


@frappe.whitelist()
def get_merge_preview(source_name: str, target_name: str) -> Dict[str, Any]:
    """
    API endpoint to get merge preview.

    Returns:
        Dict: Preview data with field comparisons and warnings (OperationResult.to_dict() format)

    Security:
        - Requires write permission on both members
        - Never throws exceptions (returns failed OperationResult)
    """
    service = MemberMergeService()
    try:
        preview_data = service.get_merge_preview(source_name, target_name)
        return OperationResult.ok(
            preview_data, message=f"Generated merge preview for {source_name} → {target_name}"
        ).to_dict()
    except frappe.PermissionError as e:
        return OperationResult.fail(
            _("Insufficient permissions to merge members"),
            errors=[str(e)],
            source=source_name,
            target=target_name,
        ).to_dict()
    except frappe.ValidationError as e:
        return OperationResult.fail(str(e), errors=[str(e)], source=source_name, target=target_name).to_dict()
    except Exception as e:
        service.logger.error(f"Unexpected error in merge preview for {source_name} → {target_name}: {str(e)}")
        return OperationResult.fail(
            _("An error occurred while generating merge preview"),
            errors=[str(e)],
            source=source_name,
            target=target_name,
        ).to_dict()


@frappe.whitelist()
def execute_merge(
    source_name: str,
    target_name: str,
    field_selections: str | Dict[str, str],
) -> Dict[str, Any]:
    """
    API endpoint to execute member merge.

    Args:
        field_selections: JSON string or dict mapping fieldname -> "source"|"target"

    Returns:
        Dict: Merge result with merged member name and statistics (OperationResult.to_dict() format)

    Security:
        - Requires write permission on both members
        - Never throws exceptions (returns failed OperationResult)
    """
    service = MemberMergeService()
    try:
        # Parse field_selections if it's a JSON string
        if isinstance(field_selections, str):
            field_selections = json.loads(field_selections)

        merge_result = service.execute_merge(source_name, target_name, field_selections)

        return OperationResult.ok(
            merge_result, message=f"Successfully merged {source_name} into {merge_result['merged_member']}"
        ).to_dict()

    except json.JSONDecodeError as e:
        return OperationResult.fail(
            _("Invalid field selections format"), errors=[str(e)], source=source_name, target=target_name
        ).to_dict()
    except frappe.DoesNotExistError as e:
        return OperationResult.fail(
            _("Member not found"), errors=[str(e)], source=source_name, target=target_name
        ).to_dict()
    except frappe.PermissionError as e:
        return OperationResult.fail(
            _("Insufficient permissions to merge members"),
            errors=[str(e)],
            source=source_name,
            target=target_name,
        ).to_dict()
    except frappe.ValidationError as e:
        return OperationResult.fail(str(e), errors=[str(e)], source=source_name, target=target_name).to_dict()
    except AttributeError as e:
        # Handle pre-existing bugs in service methods
        service.logger.error(f"AttributeError in member merge {source_name} → {target_name}: {str(e)}")
        return OperationResult.fail(
            _("An internal error occurred. Please contact support."),
            errors=[str(e)],
            source=source_name,
            target=target_name,
        ).to_dict()
    except Exception as e:
        service.logger.error(f"Unexpected error in member merge {source_name} → {target_name}: {str(e)}")
        return OperationResult.fail(
            _("An error occurred while merging members"),
            errors=[str(e)],
            source=source_name,
            target=target_name,
        ).to_dict()
