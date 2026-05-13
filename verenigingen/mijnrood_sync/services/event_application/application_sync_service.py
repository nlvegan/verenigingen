"""MijnRoodApplicationSyncService — applies membership-application events to Member rows.

Extracted from event_application_service.py as Phase 1, PR #3 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service owns:
- Application creation (admin_membership_application → Pending Member)
- Application update (changed application data)
- Application approval (correlator-synthesized Approved event)
- Application → Member promotion (shared by Approved path + apply-time
  safety net invoked from PR #2's member_sync_service)
- Field-by-field Member update from MijnRood data
- Linked-Member lookup for approved events

It delegates back to the calling event-application orchestrator for
cross-cutting helpers (create_related_records, assign_chapter_from_division,
handle_division_field_change, apply_new_member fallback) that have not
yet been extracted. The `orchestrator` parameter on public methods will
be removed once those are moved to their own services in later PRs.
"""

import logging
from typing import Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.mijnrood_sync.field_mapping import get_active_status_ids
from verenigingen.mijnrood_sync.services.event_application.mapping_service import (
    get_mapping_service,
)
from verenigingen.mijnrood_sync.utils import safe_int, safe_json_load

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.application_sync")


class MijnRoodApplicationSyncService:
    """Applies MijnRood membership-application events to Member rows."""

    _APPLICATION_FIELDS = {
        "member_id": "member_id",
        "first_name": "first_name",
        "tussenvoegsel": "tussenvoegsel",
        "last_name": "last_name",
        "email": "email",
        "contact_number": "contact_number",
        "birth_date": "birth_date",
        "iban": "iban",
        "dues_rate": "dues_rate",
        "accepts_optional_communications": "accepts_optional_communications",
    }

    def __init__(self):
        self.logger = logger

    def _set_application_fields(self, member, row_data: dict, is_new: bool = False) -> bool:
        """Apply mapped MijnRood fields to a Member document.

        Handles member_id stringification and payment method inference.

        Args:
            is_new: If True, infer payment_method from IBAN when not already set.

        Returns:
            True if any field was changed.
        """
        changed = False
        for row_key, member_field in self._APPLICATION_FIELDS.items():
            val = row_data.get(row_key)
            if val is None or val == "":
                continue
            if row_key == "member_id":
                val = str(val)
            current = member.get(member_field)
            if str(val).strip() != str(current or "").strip():
                member.set(member_field, val)
                changed = True

        # For new applications, infer payment method from IBAN
        if is_new and member.iban and not member.payment_method:
            member.payment_method = "Bank Transfer"

        # Mollie overrides payment method for both new and changed
        mollie_id = row_data.get("custom_mollie_customer_id")
        if mollie_id and mollie_id != member.mollie_customer_id:
            member.mollie_customer_id = mollie_id
            member.payment_method = "Mollie"
            changed = True

        return changed


_service_instance: Optional[MijnRoodApplicationSyncService] = None


def get_application_sync_service() -> MijnRoodApplicationSyncService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodApplicationSyncService()
    return _service_instance
