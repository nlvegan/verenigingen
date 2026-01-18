"""
Member ID Counter Management - CANONICAL IMPLEMENTATION

This module provides atomic member ID generation with database-level locking.
All other ID generation code should delegate to MemberIDManager.get_next_member_id().

Implementation Details:
    - Uses FOR UPDATE row locking for atomicity
    - Prevents duplicate IDs under concurrent member creation
    - Falls back to timestamp-based IDs on error

Consumers:
    - services/member/core/member_id_service.py (delegates here)
    - services/member/identification/member_id_service.py (delegates here)
    - Member DocType hooks (generate_member_id, validate_member_id_change)

See Also:
    - docs/audits/MEMBER_ID_CONSOLIDATION_PLAN.md
"""

import frappe
from frappe import _
from frappe.utils import cint

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class MemberIDManager:
    """Manages member ID counter with atomic database operations.

    This is the CANONICAL implementation for member ID generation.
    Uses FOR UPDATE row locking to prevent duplicate IDs under concurrent load.

    All other ID generation code should delegate to this class.
    """

    @staticmethod
    def get_next_member_id():
        """
        Get the next available member ID with atomic increment.

        Uses FOR UPDATE row locking within Frappe's existing transaction.
        Do NOT use explicit frappe.db.begin()/commit() - Frappe manages transactions
        during document lifecycle operations (before_insert, validate, etc.).

        Note: Verenigingen Settings is a Single DocType, so data is stored in
        tabSingles table, not in a dedicated tabVerenigingen Settings table.

        Returns: int - the next member ID to use
        """
        try:
            doctype_name = "Verenigingen Settings"
            field_name = "last_member_id"

            # Lock the settings row to prevent concurrent access
            # FOR UPDATE works within Frappe's existing transaction
            # Single DocTypes store data in tabSingles table
            current_id = frappe.db.sql(
                """
                SELECT value
                FROM `tabSingles`
                WHERE doctype = %s AND field = %s
                FOR UPDATE
                """,
                (doctype_name, field_name),
                as_dict=True,
            )

            if not current_id or current_id[0].value is None:
                # Initialize from existing data
                initialized_id = MemberIDManager._initialize_counter()
                # Check if row exists first
                row_exists = frappe.db.sql(
                    """
                    SELECT 1 FROM `tabSingles`
                    WHERE doctype = %s AND field = %s
                    """,
                    (doctype_name, field_name),
                )
                if row_exists:
                    frappe.db.sql(
                        """
                        UPDATE `tabSingles`
                        SET value = %s
                        WHERE doctype = %s AND field = %s
                        """,
                        (initialized_id, doctype_name, field_name),
                    )
                else:
                    frappe.db.sql(
                        """
                        INSERT INTO `tabSingles` (doctype, field, value)
                        VALUES (%s, %s, %s)
                        """,
                        (doctype_name, field_name, initialized_id),
                    )
                next_id = initialized_id + 1
            else:
                next_id = cint(current_id[0].value) + 1

            # Update to next value atomically
            frappe.db.sql(
                """
                UPDATE `tabSingles`
                SET value = %s
                WHERE doctype = %s AND field = %s
                """,
                (next_id, doctype_name, field_name),
            )

            # Update cache for performance (but don't rely on it for atomicity)
            counter_key = "member_id_counter"
            frappe.cache().set(counter_key, next_id)

            return next_id

        except Exception as e:
            frappe.log_error(f"Error generating member ID: {str(e)}", "Member ID Generation")
            # Fallback to timestamp-based ID to avoid blocking user
            import time

            fallback_id = int(time.time() * 1000) % 1000000  # Last 6 digits
            frappe.logger().warning(f"Using fallback member ID: {fallback_id}")
            return fallback_id

    @staticmethod
    def _initialize_counter():
        """Initialize the counter from existing data or settings"""

        # Check highest existing member_id (extract numeric part)
        highest_member = frappe.db.sql(
            """
            SELECT member_id
            FROM `tabMember`
            WHERE member_id IS NOT NULL
            AND member_id REGEXP '^[0-9]+$'
            ORDER BY CAST(member_id AS UNSIGNED) DESC
            LIMIT 1
        """,
            as_dict=True,
        )

        if highest_member and highest_member[0].member_id:
            return cint(highest_member[0].member_id)

        # Fall back to settings
        settings = frappe.get_single("Verenigingen Settings")
        return cint(settings.member_id_start) or 1000

    @staticmethod
    def reset_counter(new_value):
        """
        Reset the counter to a specific value
        Args:
            new_value (int): New counter value to set
        """
        if not frappe.has_permission("Member", "write"):
            frappe.throw(_("Insufficient permissions to reset member ID counter"))

        # Validate new value
        settings = frappe.get_single("Verenigingen Settings")
        min_value = cint(settings.member_id_start) or 1000

        if new_value < min_value:
            frappe.throw(_("Counter value cannot be less than the configured minimum: {0}").format(min_value))

        # Check if new value conflicts with existing member IDs
        existing_conflict = frappe.db.sql(
            """
            SELECT member_id
            FROM `tabMember`
            WHERE member_id IS NOT NULL
            AND CAST(member_id AS UNSIGNED) >= %s
            ORDER BY CAST(member_id AS UNSIGNED) ASC
            LIMIT 1
        """,
            (new_value,),
            as_dict=True,
        )

        if existing_conflict:
            frappe.msgprint(
                _(
                    "Warning: Counter reset to {0}, but member ID {1} already exists. "
                    "This may cause conflicts."
                ).format(new_value, existing_conflict[0].member_id),
                indicator="orange",
            )

        # Reset the cache counter
        counter_key = "member_id_counter"
        frappe.cache().set(counter_key, new_value)

        frappe.msgprint(_("Member ID counter reset to {0}").format(new_value), indicator="green")

    @staticmethod
    def sync_counter_with_settings():
        """
        Sync counter with Verenigingen Settings if settings value is higher
        This is called when Verenigingen Settings is updated
        """
        settings = frappe.get_single("Verenigingen Settings")
        settings_start = cint(settings.member_id_start) or 1000

        counter_key = "member_id_counter"
        current_counter = frappe.cache().get(counter_key)

        if current_counter is None:
            current_counter = MemberIDManager._initialize_counter()

        # If settings value is higher, update counter
        if settings_start > current_counter:
            frappe.cache().set(counter_key, settings_start)

            frappe.msgprint(
                _("Member ID counter updated to {0} based on Verenigingen Settings").format(settings_start),
                indicator="blue",
            )


# Hook function to be called from Member.before_insert
def generate_member_id(doc):
    """
    Generate member ID for new Member documents
    Args:
        doc: Member document
    """
    if not doc.member_id:
        # Skip system counter document
        if doc.name == "MEMBER-COUNTER-SYSTEM":
            return

        next_id = MemberIDManager.get_next_member_id()
        doc.member_id = str(next_id)

        # Log the assignment
        frappe.logger().info(f"Assigned member ID {next_id} to {doc.full_name}")


# Validation to prevent manual member_id changes that could break sequence
def validate_member_id_change(doc, method=None):
    """
    Validate member ID changes to prevent sequence conflicts
    """
    if doc.get("__islocal"):
        return  # New document, OK

    if doc.name == "MEMBER-COUNTER-SYSTEM":
        return  # System document, OK

    # Check if member_id was changed
    if doc.has_value_changed("member_id"):
        old_id = doc.get_db_value("member_id")
        new_id = doc.member_id

        # Only allow changes by System Managers
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Only System Managers can change member IDs"))

        # Validate new ID is not in use
        if new_id and frappe.db.exists("Member", {"member_id": new_id, "name": ["!=", doc.name]}):
            frappe.throw(_("Member ID {0} is already in use").format(new_id))

        # Log the change
        frappe.logger().info(
            f"Member ID changed from {old_id} to {new_id} for {doc.name} by {frappe.session.user}"
        )


# Whitelisted methods for client-side calls
@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def reset_member_id_counter(counter_value):
    """Reset the member ID counter (called from client-side)"""
    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("Insufficient permissions"))

    if not frappe.user.has_role("System Manager"):
        frappe.throw(_("Only System Managers can reset the member ID counter"))

    counter_value = cint(counter_value)
    if counter_value <= 0:
        frappe.throw(_("Counter value must be greater than 0"))

    MemberIDManager.reset_counter(counter_value)

    return {"success": True, "message": _("Member ID counter reset to {0}").format(counter_value)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.MEMBER_DATA)
def get_next_member_id_preview():
    """Get the next member ID that would be assigned"""
    if not frappe.has_permission("Member", "read"):
        frappe.throw(_("Insufficient permissions"))

    # Get next ID without incrementing the counter
    counter_key = "member_id_counter"
    current_counter = frappe.cache().get(counter_key)

    if current_counter is None:
        current_counter = MemberIDManager._initialize_counter()

    return {"next_id": current_counter + 1, "current_counter": current_counter}


# Function to get counter statistics for dashboard
@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def get_member_id_statistics():
    """Get statistics about member ID usage"""
    if not frappe.has_permission("Member", "read"):
        frappe.throw(_("Insufficient permissions"))

    stats = {}

    # Current counter value
    counter_key = "member_id_counter"
    current_counter = frappe.cache().get(counter_key)
    if current_counter is None:
        current_counter = MemberIDManager._initialize_counter()

    stats["next_id"] = current_counter + 1
    stats["current_counter"] = current_counter

    # Highest assigned ID
    highest = frappe.db.sql(
        """
        SELECT MAX(CAST(member_id AS UNSIGNED)) as highest
        FROM `tabMember`
        WHERE member_id IS NOT NULL
        AND member_id REGEXP '^[0-9]+$'
        AND name != 'MEMBER-COUNTER-SYSTEM'
    """,
        as_dict=True,
    )

    stats["highest_assigned"] = highest[0].highest if highest and highest[0].highest else 0

    # Total members with numeric IDs
    total = frappe.db.sql(
        """
        SELECT COUNT(*) as total
        FROM `tabMember`
        WHERE member_id IS NOT NULL
        AND member_id REGEXP '^[0-9]+$'
        AND name != 'MEMBER-COUNTER-SYSTEM'
    """,
        as_dict=True,
    )

    stats["total_with_numeric_ids"] = total[0].total if total else 0

    # Gap analysis
    if stats["highest_assigned"] > 0:
        gaps = frappe.db.sql(
            """
            SELECT member_id
            FROM `tabMember`
            WHERE member_id IS NOT NULL
            AND member_id REGEXP '^[0-9]+$'
            AND name != 'MEMBER-COUNTER-SYSTEM'
            ORDER BY CAST(member_id AS UNSIGNED)
        """,
            as_dict=True,
        )

        used_ids = [int(g.member_id) for g in gaps]
        all_ids = set(range(min(used_ids), max(used_ids) + 1))
        gaps_found = all_ids - set(used_ids)
        stats["gaps"] = sorted(list(gaps_found))[:10]  # Show first 10 gaps
        stats["gap_count"] = len(gaps_found)
    else:
        stats["gaps"] = []
        stats["gap_count"] = 0

    return stats
