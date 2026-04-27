"""
Re-export shim for member_import_cleanup.

The implementation lives at scripts/migration/member_import_cleanup.py (moved
in commit 9018fb82). This shim preserves the verenigingen.utils.* import path
required by admin_tools.execute_admin_tool, which only accepts module paths
starting with "verenigingen." or "frappe." (see admin_tools.py:736).

Re-exporting the function objects keeps frappe.whitelist set membership intact,
since the whitelist check is by object identity.
"""

from scripts.migration.member_import_cleanup import (
    cleanup_all_test_data,
    cleanup_test_members_only,
    force_cleanup_orphaned_schedules_and_invoices,
    nuclear_cleanup_all_members,
    nuclear_truncate_member_tables,
    preview_member_cleanup,
    scan_and_clear_broken_links,
)

__all__ = [
    "cleanup_all_test_data",
    "cleanup_test_members_only",
    "force_cleanup_orphaned_schedules_and_invoices",
    "nuclear_cleanup_all_members",
    "nuclear_truncate_member_tables",
    "preview_member_cleanup",
    "scan_and_clear_broken_links",
]
