#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cache Invalidation Hooks for Verenigingen
==========================================

Automatic cache invalidation when member, board, or chapter data changes.
Ensures consistent data across reports and utilities by clearing relevant caches.

Integration:
    Add these hooks to frappe hooks.py to trigger automatic invalidation:

    doc_events = {
        "Member": {
            "after_insert": "verenigingen.utils.cache_invalidation_hooks.invalidate_member_cache",
            "on_update": "verenigingen.utils.cache_invalidation_hooks.invalidate_member_cache",
            "on_trash": "verenigingen.utils.cache_invalidation_hooks.invalidate_member_cache",
        },
        "Verenigingen Chapter Board Member": {
            "after_insert": "verenigingen.utils.cache_invalidation_hooks.invalidate_chapter_access_cache",
            "on_update": "verenigingen.utils.cache_invalidation_hooks.invalidate_chapter_access_cache",
            "on_trash": "verenigingen.utils.cache_invalidation_hooks.invalidate_chapter_access_cache",
        },
        "Payment Entry": {
            "on_submit": "verenigingen.utils.cache_invalidation_hooks.invalidate_payment_cache",
            "on_cancel": "verenigingen.utils.cache_invalidation_hooks.invalidate_payment_cache",
        }
    }
"""

from typing import Optional

import frappe


def invalidate_member_cache(doc, method=None):
    """
    Invalidate member-related caches when member data changes.

    Args:
        doc: Member document that changed
        method: Frappe hook method name (not used)
    """
    try:
        member_name = doc.name if hasattr(doc, "name") else str(doc)

        # Clear member-specific caches
        cache_patterns = [
            f"member_chapters:{member_name}",
            f"member_volunteer:{member_name}",
            "member_board_positions:*",  # Wildcard for all users since member could be linked to multiple
            "user_accessible_chapters:*",  # Wildcard since member changes could affect multiple users
        ]

        for pattern in cache_patterns:
            try:
                if "*" in pattern:
                    # delete_keys() resolves the wildcard and deletes with
                    # make_keys=False. The previous get_keys() + delete_key() loop
                    # double-prefixed every key -- get_keys() returns keys with the
                    # site namespace already applied, delete_key() re-applies it -- so
                    # this branch silently deleted nothing.
                    #
                    # The pattern is passed through unchanged: get_keys() appends its
                    # OWN "*" (redis_wrapper.py, `key = self.make_key(key + "*")`), so
                    # "member_*" globs "member_**", which Redis treats identically to
                    # "member_*". Stripping the trailing star would be a no-op that
                    # reads as if it were load-bearing.
                    frappe.cache().delete_keys(pattern)
                else:
                    frappe.cache().delete_key(pattern)
            except (ConnectionError, TimeoutError) as cache_error:
                frappe.logger().warning(f"Cache invalidation failed for pattern '{pattern}': {cache_error}")
            except Exception as e:
                frappe.logger().error(f"Unexpected cache error for pattern '{pattern}': {e}")

        frappe.logger().info(f"Member cache invalidated for {member_name}")

    except Exception as e:
        frappe.logger().error(f"Error invalidating member cache: {str(e)}")


def invalidate_chapter_access_cache(doc, method=None):
    """
    Invalidate chapter access caches when board positions change.

    Args:
        doc: Chapter Board Member document that changed
        method: Frappe hook method name (not used)
    """
    try:
        # Get affected user from volunteer -> member -> user chain
        volunteer_name = getattr(doc, "volunteer", None)
        if not volunteer_name:
            frappe.logger().warning("No volunteer found for board member change")
            return

        # Get member from volunteer
        member_name = frappe.db.get_value("Volunteer", volunteer_name, "member")
        if not member_name:
            frappe.logger().warning(f"No member found for volunteer {volunteer_name}")
            return

        # Get user from member
        user_email = frappe.db.get_value("Member", member_name, "user")
        if not user_email:
            frappe.logger().warning(f"No user found for member {member_name}")
            return

        # Clear chapter access caches for affected user
        cache_patterns = [
            f"user_accessible_chapters:{user_email}",
            f"user_board_positions:{user_email}",
            f"chapter_permissions:{user_email}",
        ]

        for pattern in cache_patterns:
            try:
                frappe.cache().delete_key(pattern)
            except (ConnectionError, TimeoutError) as cache_error:
                frappe.logger().warning(f"Cache invalidation failed for '{pattern}': {cache_error}")
            except Exception as e:
                frappe.logger().error(f"Unexpected cache error for '{pattern}': {e}")

        # Also clear general chapter access cache since board structure changed.
        # delete_keys() rather than get_keys() + delete_key(): the latter
        # double-prefixed every key and deleted nothing.
        try:
            frappe.cache().delete_keys("user_accessible_chapters:*")
        except Exception as e:
            frappe.logger().warning(f"Error clearing general chapter access cache: {e}")

        frappe.logger().info(f"Chapter access cache invalidated for user {user_email} (member {member_name})")

    except Exception as e:
        frappe.logger().error(f"Error invalidating chapter access cache: {str(e)}")


def invalidate_payment_cache(doc, method=None):
    """
    Invalidate payment caches when payment entries change.

    Args:
        doc: Payment Entry document that changed
        method: Frappe hook method name (not used)
    """
    try:
        # Get customer/party from payment entry
        party = getattr(doc, "party", None)
        party_type = getattr(doc, "party_type", None)

        if party_type != "Customer":
            return  # Only handle customer payments

        if not party:
            frappe.logger().warning("No party found for payment entry change")
            return

        # Import cache invalidation function from payment_utils
        try:
            from verenigingen.utils.payment_utils import invalidate_payment_cache

            invalidate_payment_cache(party)
        except ImportError:
            frappe.logger().warning("Payment utils not available for cache invalidation")

        frappe.logger().info(f"Payment cache invalidated for customer {party}")

    except Exception as e:
        frappe.logger().error(f"Error invalidating payment cache: {str(e)}")


def invalidate_all_caches():
    """
    Emergency function to clear all verenigingen-related caches.
    Use sparingly as this affects performance.
    """
    try:
        cache_patterns = [
            "member_*",
            "user_accessible_chapters:*",
            "user_board_positions:*",
            "chapter_permissions:*",
            "payment_summary:*",
            "payment_history:*",
            "payment_years:*",
            "unreconciled_payments:*",
        ]

        total_cleared = 0
        for pattern in cache_patterns:
            try:
                # One scan, then delete exactly those keys. The previous
                # get_keys() + delete_key() loop incremented total_cleared for every
                # key while deleting none of them (delete_key re-applies the site
                # namespace that get_keys already applied), so this "emergency clear
                # everything" function reported a confident non-zero count and was a
                # complete no-op.
                #
                # This is what delete_keys() does internally; it is inlined here only
                # so the count comes from the same scan that performed the delete.
                # Scanning twice would both double the cost (get_keys uses Redis KEYS,
                # which is O(keyspace) and blocking) and let the count drift from what
                # was actually removed.
                keys = frappe.cache().get_keys(pattern)
                frappe.cache().delete_value(keys, make_keys=False)
                total_cleared += len(keys)
            except Exception as e:
                frappe.logger().warning(f"Error clearing cache pattern '{pattern}': {e}")

        frappe.logger().info(f"Emergency cache clear completed: {total_cleared} keys cleared")

    except Exception as e:
        frappe.logger().error(f"Error during emergency cache clear: {str(e)}")


def get_cache_statistics():
    """
    Get statistics about verenigingen cache usage for monitoring.

    Returns:
        Dict with cache statistics or None if unavailable
    """
    try:
        cache_patterns = [
            "member_*",
            "user_accessible_chapters:*",
            "payment_summary:*",
        ]

        stats = {"total_keys": 0, "pattern_counts": {}, "cache_available": True}

        for pattern in cache_patterns:
            try:
                keys = frappe.cache().get_keys(pattern)
                pattern_count = len(keys)
                stats["pattern_counts"][pattern] = pattern_count
                stats["total_keys"] += pattern_count
            except Exception:
                stats["pattern_counts"][pattern] = "unavailable"

        return stats

    except Exception as e:
        frappe.logger().error(f"Error getting cache statistics: {str(e)}")
        return {"error": str(e), "cache_available": False}
