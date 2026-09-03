# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MembershipImportService - Service for creating membership records during CSV import.

Extracts membership creation logic from MijnRood CSV Import DocType
into a dedicated service with proper concurrency handling.
"""

import time
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.csv.data_transformers import (
    determine_membership_type_for_csv_import,
    get_dues_schedule_template_from_payment_period,
)
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS


class MembershipImportService(StatelessService):
    """Service for creating Membership records during CSV import.

    Handles membership creation with proper concurrency control via
    advisory locks to prevent duplicate memberships when multiple
    imports run concurrently.
    """

    def __init__(self):
        """Initialize the MembershipImportService."""
        super().__init__(service_name="MembershipImportService")

    def create_membership_from_csv(
        self,
        member_doc: Document,
        row_data: Dict[str, Any],
    ) -> Optional[str]:
        """Create Membership record for imported member.

        Uses advisory locking to prevent duplicate memberships when
        multiple imports run concurrently for the same member.

        Args:
            member_doc: Member document to create membership for
            row_data: Dictionary containing CSV row data with fields:
                - member_since: Historic start date
                - dues_rate: Custom dues rate (optional)
                - payment_period: Payment frequency

        Returns:
            Membership name if created, None if skipped or failed
        """
        lock_name = f"membership_create_{member_doc.name}"
        lock_acquired = False

        try:
            # Acquire advisory lock
            lock_result = frappe.db.sql("SELECT GET_LOCK(%s, 5) as acquired", lock_name, as_dict=True)
            lock_acquired = lock_result and lock_result[0].acquired == 1

            if not lock_acquired:
                self.logger.warning(f"Could not acquire lock for membership creation for {member_doc.name}")
                # Wait and check if another process created it
                time.sleep(1)
                existing = self._get_existing_active_membership(member_doc.name)
                if existing:
                    self.logger.info(
                        f"Membership {existing} was created by concurrent process for {member_doc.name}"
                    )
                    return existing

            # Double-check under lock for existing membership
            existing_membership = self._get_existing_active_membership(member_doc.name)
            if existing_membership:
                self.logger.info(
                    f"Member {member_doc.name} already has active membership "
                    f"{existing_membership}, skipping creation"
                )
                return existing_membership

            # Create membership using unified path
            self.logger.info(f"[CSV IMPORT] Creating membership for {member_doc.name}")
            membership_name = self._create_membership_unified_path(member_doc, row_data)

            if membership_name:
                # Update member's current membership reference
                member_doc.reload()
                member_doc.current_membership_plan = membership_name
                member_doc._system_update = True
                member_doc.save()

            return membership_name

        except NON_RESUMABLE_DB_ERRORS:
            # 1213/1205: the transaction is already gone (or half-applied). Swallowing
            # this into a `return None` -- the caller then raises its own
            # ValidationError, which every guard keyed on the original error's TYPE
            # (including #700's row-loop guard) cannot see through. Let it propagate.
            raise
        except Exception as e:
            frappe.log_error(
                f"ERROR in create_membership_from_csv for {member_doc.name}: {str(e)}\n"
                f"{frappe.get_traceback()}",
                "CSV Import - Membership Creation Failed",
            )
            return None

        finally:
            if lock_acquired:
                try:
                    frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)
                except Exception:
                    pass

    def _get_existing_active_membership(self, member_name: str) -> Optional[str]:
        """Check if member already has an active membership."""
        return frappe.db.get_value(
            "Membership",
            {"member": member_name, "docstatus": 1, "status": "Active"},
            "name",
        )

    def _create_membership_unified_path(
        self,
        member_doc: Document,
        row_data: Dict[str, Any],
    ) -> Optional[str]:
        """Create membership using unified normal approval workflow."""
        # Determine membership type
        membership_type = self.determine_membership_type(row_data)

        if not membership_type:
            frappe.throw(f"Could not determine membership type for member: {row_data.get('member_id')}")

        # Set member fields for unified path
        member_doc.selected_membership_type = membership_type

        # Resolve dues schedule template from CSV payment period (Betaalperiode)
        # This uses csv_monthly/quarterly/annual_dues_schedule from Verenigingen Settings
        if row_data.get("payment_period"):
            try:
                template_name = get_dues_schedule_template_from_payment_period(row_data)
                member_doc.application_dues_schedule = template_name
                self.logger.info(
                    f"[CSV IMPORT] Using template '{template_name}' for payment period "
                    f"'{row_data['payment_period']}' for {member_doc.name}"
                )
            except Exception as e:
                self.logger.warning(
                    f"[CSV IMPORT] Could not resolve template for payment period "
                    f"'{row_data.get('payment_period')}': {e}. "
                    f"Falling back to membership type default template."
                )

        # Use normal approval workflow with CSV-specific parameters
        membership_doc = member_doc.create_membership_on_approval(
            start_date=row_data.get("member_since"),
            create_invoice=False,  # No backfill invoices for historic imports
            custom_dues_rate=row_data.get("dues_rate"),
            custom_rate_reason="Imported from CSV with custom rate",
            is_csv_import=True,  # Flag for proper renewal_date calculation
        )

        if membership_doc:
            self.logger.info(f"Created membership {membership_doc.name} for member {member_doc.name}")
            return membership_doc.name

        return None

    def determine_membership_type(self, row_data: Dict[str, Any]) -> str:
        """Determine membership type from CSV row data.

        Maps CSV membership type values (like 'aspirant', 'lid') to
        actual Membership Type document names.

        Args:
            row_data: Dictionary containing CSV row data

        Returns:
            Membership Type document name (e.g., 'Regular', 'Aspirant')
        """
        return determine_membership_type_for_csv_import(row_data)

    def get_dues_schedule_template(self, row_data: Dict[str, Any]) -> str:
        """Get dues schedule template based on payment period.

        Args:
            row_data: Dictionary containing payment_period field

        Returns:
            Dues Schedule Template name
        """
        return get_dues_schedule_template_from_payment_period(row_data)


# Module-level singleton accessor
_service_instance: Optional[MembershipImportService] = None


def get_membership_import_service() -> MembershipImportService:
    """Get singleton instance of MembershipImportService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MembershipImportService()
    return _service_instance
