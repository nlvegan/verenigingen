"""
Chapter Provisioning Service

Ensures chapters and their required region exist. Used by:
- MijnRood CSV Import (auto_create_chapters flag)
- MijnRood Sync Event application (division → chapter sync)

Extracted from MijnRoodCSVImport._create_chapter_if_not_exists and
_ensure_nl_region_exists to make the logic reusable.
"""

from typing import Optional

import frappe
from frappe import _
from frappe.query_builder.functions import Lower


def ensure_region(default_region: Optional[str] = None) -> Optional[str]:
    """Ensure a region exists for chapter creation.

    Priority:
    1. Use default_region if specified and exists
    2. Find existing region with code/name matching NL/nederland/netherlands
    3. Create basic Netherlands region as fallback

    Args:
        default_region: Explicit region name to use. If set but doesn't exist, raises.

    Returns:
        Region name, or None on unexpected failure.
    """
    # Priority 1: explicit default
    if default_region:
        if frappe.db.exists("Region", default_region):
            return default_region
        frappe.throw(
            _("Default region '{0}' does not exist. Create it first or leave the field empty.").format(
                default_region
            )
        )

    # Priority 2: find existing NL region
    Region = frappe.qb.DocType("Region")
    nl_names = ["nl", "nederland", "netherlands"]
    result = (
        frappe.qb.from_(Region)
        .select(Region.name)
        .where((Lower(Region.region_code).isin(nl_names)) | (Lower(Region.region_name).isin(nl_names)))
        .limit(1)
        .run()
    )
    if result and result[0]:
        return result[0][0]

    # Priority 3: create Netherlands region
    region = frappe.new_doc("Region")
    region.region_name = "Netherlands"
    region.region_code = "NL"
    region.is_active = 1
    region.preferred_language = "Dutch"
    region.time_zone = "Europe/Amsterdam"
    region.membership_fee_adjustment = 1.0
    region.description = "Auto-created Netherlands region. Please update with proper details."
    region._csv_import = True
    region.flags.ignore_workflow = True
    # Security: System-internal provisioning of reference data
    region.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.logger().info("Auto-created Netherlands region '%s'", region.name)
    return region.name


def ensure_chapter(
    chapter_name: str,
    default_region: Optional[str] = None,
    introduction: Optional[str] = None,
    published: int = 0,
    mijnrood_division_id: Optional[int] = None,
    contact_email: Optional[str] = None,
) -> Optional[str]:
    """Create a chapter if it doesn't exist, ensuring the required region is present.

    Args:
        chapter_name: Name for the chapter (used as document name).
        default_region: Explicit region to use. Falls back to NL auto-detection.
        introduction: Chapter introduction text. Auto-generated if omitted.
        published: Whether the chapter is published (visible on application form).
        mijnrood_division_id: MijnRood division ID to set on the chapter.
        contact_email: Chapter contact email.

    Returns:
        Chapter name if created or already exists, None on failure.
    """
    if frappe.db.exists("Chapter", chapter_name):
        return chapter_name

    try:
        region_name = ensure_region(default_region)
        if not region_name:
            frappe.logger().error("Cannot create chapter '%s' — no region available", chapter_name)
            return None

        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": chapter_name,
                "__newname": chapter_name,  # autoname="prompt" requires this
                "status": "Active",
                "region": region_name,
                "published": published,
                "introduction": introduction
                or f"Auto-created chapter '{chapter_name}'. Please update with proper details.",
                "mijnrood_division_id": mijnrood_division_id,
                "contact_email": contact_email,
            }
        )
        chapter._csv_import = True
        chapter.flags.ignore_workflow = True
        # Security: System-internal provisioning from authoritative sync data
        chapter.insert(ignore_permissions=True)
        # Commit immediately: background jobs triggered by member assignment
        # need to see this chapter, otherwise "Chapter X not found" errors
        frappe.db.commit()

        frappe.logger().info(
            "Auto-created chapter '%s' (region=%s, division_id=%s)",
            chapter_name,
            region_name,
            mijnrood_division_id,
        )
        return chapter.name

    except Exception as e:
        frappe.logger().error("Failed to create chapter '%s': %s", chapter_name, e)
        frappe.log_error(
            title=f"Chapter Auto-Creation Failed: {chapter_name}",
            message=str(e),
        )
        return None
