"""
Bulk Operation Context Managers for Notification Suppression

Provides safe, explicit context managers for suppressing notifications during
bulk operations. This prevents accidental email floods and makes bulk operation
intent clear in code.

Example usage:
    with suppress_chapter_notifications():
        for member in bulk_member_list:
            ChapterMembershipManager.assign_member_to_chapter(member, chapter)
            # Notifications automatically suppressed within this block
"""

from contextlib import contextmanager
from typing import Iterator

import frappe


@contextmanager
def suppress_chapter_notifications() -> Iterator[None]:
    """
    Context manager to suppress chapter-related notifications during bulk operations.

    This ensures that:
    1. Chapter assignment notifications are suppressed
    2. Original notification settings are restored after the block
    3. Suppression is scoped to the with-block only

    Usage:
        with suppress_chapter_notifications():
            for member in members:
                ChapterMembershipManager.assign_member_to_chapter(
                    member_id=member.name,
                    chapter_name=chapter_name,
                    # notify parameter not needed - auto-suppressed
                )

    Note: This sets notify=False internally via ChapterMembershipManager logic.
    The global setting is temporarily overridden within this context.
    """
    # Store original setting
    settings = frappe.get_single("Verenigingen Settings")
    original_value = getattr(settings, "send_chapter_assignment_notifications", False)

    # Create temporary flag for context
    original_flag = getattr(frappe.flags, "suppress_chapter_notifications", False)

    try:
        # Suppress notifications within this context
        frappe.flags.suppress_chapter_notifications = True

        # Temporarily disable global setting (in-memory only)
        # This ensures ChapterMembershipManager sees notifications as disabled
        settings.send_chapter_assignment_notifications = 0

        frappe.logger().info("[BULK OPERATION] Chapter notifications suppressed (context manager active)")

        yield

    finally:
        # Always restore original values
        frappe.flags.suppress_chapter_notifications = original_flag
        settings.send_chapter_assignment_notifications = original_value

        frappe.logger().info("[BULK OPERATION] Chapter notifications restored to original setting")


@contextmanager
def suppress_all_notifications() -> Iterator[None]:
    """
    Context manager to suppress ALL notifications during bulk operations.

    Use this for large-scale imports where no notifications should be sent.
    More aggressive than suppress_chapter_notifications().

    Usage:
        with suppress_all_notifications():
            # All notification types suppressed here
            for member in members:
                process_member(member)
    """
    # Store all original settings
    settings = frappe.get_single("Verenigingen Settings")
    original_chapter = getattr(settings, "send_chapter_assignment_notifications", False)

    # Store original flags
    original_flags = {
        "suppress_notifications": getattr(frappe.flags, "suppress_notifications", False),
        "suppress_chapter_notifications": getattr(frappe.flags, "suppress_chapter_notifications", False),
    }

    try:
        # Suppress all notifications
        frappe.flags.suppress_notifications = True
        frappe.flags.suppress_chapter_notifications = True

        # Disable settings (in-memory only)
        settings.send_chapter_assignment_notifications = 0

        frappe.logger().info("[BULK OPERATION] All notifications suppressed (aggressive mode active)")

        yield

    finally:
        # Restore all original values
        for flag_name, original_value in original_flags.items():
            setattr(frappe.flags, flag_name, original_value)

        settings.send_chapter_assignment_notifications = original_chapter

        frappe.logger().info("[BULK OPERATION] All notifications restored to original settings")


def is_bulk_operation_active() -> bool:
    """
    Check if code is currently executing within a bulk operation context.

    Returns:
        bool: True if within suppress_chapter_notifications() or suppress_all_notifications()
    """
    return getattr(frappe.flags, "suppress_notifications", False) or getattr(
        frappe.flags, "suppress_chapter_notifications", False
    )
