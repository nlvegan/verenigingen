# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterEventService - Chapter change detection and event emission

This service handles detection of changes to Chapter records and emission of
corresponding events for background processing and audit trails.

Extracted from chapter.py:
- _detect_and_emit_board_changes() - Lines 604-663 (60 LOC)
- _detect_and_emit_membership_changes() - Lines 665-680 (16 LOC)
- _detect_and_emit_settings_changes() - Lines 682-703 (22 LOC)

Architecture:
- Static methods for stateless operations
- Chapter document and old_doc passed as parameters
- Event emission for background processing
- Set-based change detection for efficiency

Business Logic:
- Detects board member additions, removals, role changes
- Detects chapter membership changes (joins/leaves)
- Detects important settings field changes
- Emits events with action metadata and changed_by tracking

Dependencies:
- verenigingen.events.chapter_events for event emission
- frappe.session for user tracking
"""

from typing import TYPE_CHECKING

import frappe

from verenigingen.events.chapter_events import (
    emit_chapter_board_changed,
    emit_chapter_membership_changed,
    emit_chapter_settings_changed,
)

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterEventService:
    """
    Service for detecting Chapter changes and emitting events.

    This service handles:
    - Board member change detection (add/remove/role change)
    - Chapter membership change detection (join/leave)
    - Settings change detection for important fields
    - Event emission with action metadata
    """

    @staticmethod
    def detect_and_emit_board_changes(chapter_doc: "Document", old_doc: "Document") -> None:
        """
        Detect and emit board member changes including activation/deactivation.

        Change Detection Logic:
            - Compares old and new board member sets (volunteer, role tuples)
            - Detects new members, removed members, and role changes
            - Only considers active board members (is_active=1)

        Events Emitted:
            - "added": New board member or reactivated member
            - "role_changed": Existing member changed role
            - "removed": Board member removed or deactivated

        Args:
            chapter_doc: Current Chapter document instance
            old_doc: Previous version of the document for comparison

        Example:
            >>> ChapterEventService.detect_and_emit_board_changes(chapter_doc, old_doc)
            # Emits events for any board member changes
        """
        # Include is_active status in comparison to detect activation/deactivation
        old_board = {(bm.volunteer, bm.chapter_role) for bm in (old_doc.board_members or []) if bm.is_active}
        new_board = {
            (bm.volunteer, bm.chapter_role) for bm in (chapter_doc.board_members or []) if bm.is_active
        }

        # Find added/activated board members
        for volunteer, role in new_board - old_board:
            # Check if it's a new member or role change
            old_volunteer_roles = {
                bm.chapter_role
                for bm in (old_doc.board_members or [])
                if bm.volunteer == volunteer and bm.is_active
            }

            if not old_volunteer_roles:
                # New board member or reactivated
                emit_chapter_board_changed(
                    chapter_doc.name,
                    {
                        "volunteer": volunteer,
                        "action": "added",
                        "role": role,
                        "changed_by": frappe.session.user,
                    },
                )
            else:
                # Role change
                old_role = list(old_volunteer_roles)[0]  # Assume one role per volunteer
                emit_chapter_board_changed(
                    chapter_doc.name,
                    {
                        "volunteer": volunteer,
                        "action": "role_changed",
                        "role": role,
                        "old_role": old_role,
                        "changed_by": frappe.session.user,
                    },
                )

        # Find removed/deactivated board members
        for volunteer, role in old_board - new_board:
            # Check if completely removed or just role changed
            new_volunteer_roles = {
                bm.chapter_role
                for bm in (chapter_doc.board_members or [])
                if bm.volunteer == volunteer and bm.is_active
            }

            if not new_volunteer_roles:
                # Completely removed or deactivated
                emit_chapter_board_changed(
                    chapter_doc.name,
                    {
                        "volunteer": volunteer,
                        "action": "removed",
                        "old_role": role,
                        "changed_by": frappe.session.user,
                    },
                )

    @staticmethod
    def detect_and_emit_membership_changes(chapter_doc: "Document", old_doc: "Document") -> None:
        """
        Detect and emit chapter membership changes (joins and leaves).

        Change Detection Logic:
            - Compares old and new member sets
            - Detects new members (joins)
            - Detects removed members (leaves)

        Events Emitted:
            - "joined": New member added to chapter
            - "left": Member removed from chapter

        Args:
            chapter_doc: Current Chapter document instance
            old_doc: Previous version of the document for comparison

        Example:
            >>> ChapterEventService.detect_and_emit_membership_changes(chapter_doc, old_doc)
            # Emits events for members joining or leaving
        """
        old_members = {cm.member for cm in (old_doc.members or [])}
        new_members = {cm.member for cm in (chapter_doc.members or [])}

        # Find new members
        for member in new_members - old_members:
            emit_chapter_membership_changed(
                chapter_doc.name,
                {"member": member, "action": "joined", "changed_by": frappe.session.user},
            )

        # Find removed members
        for member in old_members - new_members:
            emit_chapter_membership_changed(
                chapter_doc.name,
                {"member": member, "action": "left", "changed_by": frappe.session.user},
            )

    @staticmethod
    def detect_and_emit_settings_changes(chapter_doc: "Document", old_doc: "Document") -> None:
        """
        Detect and emit chapter settings changes for important fields.

        Monitored Fields:
            - published: Chapter publication status
            - enable_board_role_specific_profiles: Board role configuration
            - default_board_role_profile: Default role profile
            - introduction: Chapter description
            - image: Chapter image
            - postal_codes: Geographic coverage
            - region: Chapter region

        Events Emitted:
            - "settings_changed": With list of changed fields

        Args:
            chapter_doc: Current Chapter document instance
            old_doc: Previous version of the document for comparison

        Business Logic:
            Only emits event if at least one important field changed.
            Uses Frappe's has_value_changed() for reliable change detection.

        Example:
            >>> ChapterEventService.detect_and_emit_settings_changes(chapter_doc, old_doc)
            # Emits event if any important settings changed
        """
        # Important fields that trigger settings change events
        important_fields = [
            "published",
            "enable_board_role_specific_profiles",
            "default_board_role_profile",
            "introduction",
            "image",
            "postal_codes",
            "region",
        ]

        changed_fields = []
        for field in important_fields:
            if chapter_doc.has_value_changed(field):
                changed_fields.append(field)

        if changed_fields:
            emit_chapter_settings_changed(
                chapter_doc.name,
                {"changed_fields": changed_fields, "changed_by": frappe.session.user},
            )


def get_chapter_event_service() -> ChapterEventService:
    """Get singleton instance of ChapterEventService"""
    return ChapterEventService()
