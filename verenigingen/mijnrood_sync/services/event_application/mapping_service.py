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


_service_instance: Optional[MijnRoodMappingService] = None


def get_mapping_service() -> MijnRoodMappingService:
    """Singleton accessor — mirrors existing project convention."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MijnRoodMappingService()
    return _service_instance
