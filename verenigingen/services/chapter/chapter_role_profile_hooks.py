"""
Chapter Role Profile Hooks

Hooks for Chapter DocType events that trigger role profile recalculation.
Detects removed board members by comparing child table state.

Author: Verenigingen Development Team
Last Updated: 2025-10-09
"""

import frappe


def invalidate_chapter_profile_cache(doc, method):
    """
    Hook called when Chapter is updated.

    Invalidates profile configuration cache for this chapter.

    Args:
        doc: Chapter document
        method: Hook method name
    """
    from verenigingen.utils.user_role_profile_calculator import invalidate_profile_config_cache

    # Invalidate this chapter's profile config cache
    invalidate_profile_config_cache(entity_type="chapter", entity_name=doc.name)


def on_chapter_board_members_change(doc, method):
    """DEPRECATED: Role profile sync is now handled by BoardManager.

    Kept as a no-op to avoid import errors from any remaining references.
    The BoardManager.handle_board_member_additions/changes/deletions methods
    call _sync_role_profile_for_volunteer() directly, which is reliable
    (unlike has_value_changed on child tables).
    """
    pass
