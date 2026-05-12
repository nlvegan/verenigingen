"""MijnRoodMappingService — translates MijnRood row dicts into Member field dicts.

Extracted from event_application_service.py as Phase 1, PR #1 of the
Tier C refactor (see docs/plans/2026-05-12-event-application-service-
refactor-design.md).

The service is stateless and read-only — it performs lookups in Chapter
and MijnRood Sync State for division resolution, and consults the
Settings child tables (status / role mapping) via field_mapping.py
helpers, but writes nothing.
"""

import json
import logging
from typing import Any, Optional

import frappe

from verenigingen.mijnrood_sync.field_mapping import (
    MIJNROOD_TO_MEMBER_FIELD_MAP,
    get_status_id_map,
    get_verenigingen_membership_type_for_status_id,
)
from verenigingen.mijnrood_sync.utils import safe_int

logger = logging.getLogger("verenigingen.mijnrood_sync.event_application.mapping")


def extract_email(value: Any) -> Optional[str]:
    """Return value only if it looks like an email address.

    MijnRood's email_id column may contain a numeric FK rather than
    an actual email string. Passing a bare number to a Frappe Data
    field with options=Email causes a validation error.
    """
    if not value or not isinstance(value, str):
        return None
    if "@" not in value:
        return None
    return value


class MijnRoodMappingService:
    """Translates MijnRood DB rows to Member field dicts. Stateless."""

    def resolve_division_id(self, division_id: int) -> Optional[str]:
        """Resolve a MijnRood division_id to a Chapter name.

        Checks the Chapter's mijnrood_division_id field first (direct lookup),
        then falls back to Sync State for chapters that predate the ID field.
        """
        # Direct lookup via the ID field on Chapter
        chapter_name = frappe.db.get_value("Chapter", {"mijnrood_division_id": division_id}, "name")
        if chapter_name:
            return chapter_name

        # Fallback: resolve via stored sync state raw data
        state = frappe.db.get_value(
            "MijnRood Sync State",
            {"mijnrood_table": "admin_division", "mijnrood_row_id": division_id},
            "raw_data",
        )
        if state:
            data = json.loads(state)
            return data.get("name")
        return None

    def map_member_fields(self, mijnrood_data: dict) -> dict:
        """Map MijnRood database row to intermediate field names.

        These intermediate names match what MemberImportService.update_member_fields()
        expects (same names as csv_data_validator.py FIELD_MAPPING values).

        Raises ValueError when current_membership_status_id has no mapping
        configured — operator must add the mapping and re-apply the event.
        """
        row_data: dict = {}
        for mijnrood_col, member_field in MIJNROOD_TO_MEMBER_FIELD_MAP.items():
            value = mijnrood_data.get(mijnrood_col)
            if value is not None and value != "":
                row_data[member_field] = value

        # Convert status ID to membership type — prefer explicit mapping,
        # fall back to status string, then fail loudly if neither matches.
        status_id = safe_int(mijnrood_data.get("current_membership_status_id"))
        if status_id:
            explicit_type = get_verenigingen_membership_type_for_status_id(status_id)
            if explicit_type:
                row_data["membership_type"] = explicit_type
            else:
                status_id_map = get_status_id_map()
                if status_id in status_id_map:
                    row_data["membership_type"] = status_id_map[status_id]
                else:
                    # Fail the event instead of silently importing a member
                    # without a membership type. Operator fixes the mapping,
                    # then re-runs. (Tier A audit guarantee.)
                    raise ValueError(
                        f"MijnRood status ID {status_id} (member {mijnrood_data.get('id')}) "
                        f"has no mapping configured. Add it under "
                        f"MijnRood Sync Settings → Lidmaatschapstypes, then re-apply this event."
                    )

        # Convert contribution amount from cents to euros
        cents = safe_int(mijnrood_data.get("contribution_per_period_in_cents"))
        if cents:
            row_data["dues_rate"] = cents / 100.0

        # Convert contribution period integer to Dutch string for template resolution
        # MijnRood: 0=Monthly, 1=Quarterly, 2=Annually (see Member.php constants)
        period_int = safe_int(mijnrood_data.get("contribution_period"))
        period_map = {0: "Maandelijks", 1: "Per kwartaal", 2: "Jaarlijks"}
        if period_int is not None:
            if period_int in period_map:
                row_data["payment_period"] = period_map[period_int]
            else:
                logger.warning(
                    "Unknown contribution_period value %s for MijnRood ID %s",
                    period_int,
                    mijnrood_data.get("id"),
                )

        return row_data


_service_instance: Optional[MijnRoodMappingService] = None


def get_mapping_service() -> MijnRoodMappingService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodMappingService()
    return _service_instance
