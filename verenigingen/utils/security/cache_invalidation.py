"""
Security Framework Cache Invalidation Hooks

Handles intelligent cache invalidation for the security framework when user roles
or role profiles are updated, ensuring cached security data stays fresh without
compromising performance.
"""

import frappe


def invalidate_user_role_cache_on_user_update(doc, method):
    """
    Hook for User doctype: invalidate the role-profile cache on every User save.

    This hook is triggered on User save/update operations (`on_update` also
    fires on insert -- see hooks/doc_events.py -- so no separate after_insert
    registration is needed).

    #693: this previously fired only when
    ``doc.has_value_changed("role_profile_name")`` was True, which misses
    almost every real writer of a user's roles/role profile in this app:

    - Every role GRANT/WITHDRAWAL goes through
      ``user_doc.append("roles", ...)`` / ``user_doc.roles.remove(...)`` +
      ``user_doc.save()`` (ChapterBoardMember.assign_board_member_role,
      ``withdraw_board_member_role_if_unseated``, member_role_service, ...).
      None of those touch ``role_profile_name`` at all, and "Has Role" is a
      child table whose own doc_events never fire for rows written through
      the parent User save (see hooks/doc_events.py's CHILD TABLES note) --
      so this User handler is the ONLY doc event any of them dispatch.
    - Frappe v16 moves role-profile assignment into the ``role_profiles``
      child table (``User.move_role_profile_name_to_role_profiles()``), so a
      v16 profile change can leave ``role_profile_name`` itself unchanged.

    A narrower field-level check can't be made reliable either:
    ``has_value_changed`` on a Table field (``role_profiles``) compares lists
    of child Document objects from two different in-memory loads by identity,
    which is not a meaningful equality test. So this invalidates
    unconditionally on every save rather than trying to enumerate every field
    that can carry a role change -- the cost is one extra Redis delete on a
    save that touched neither role, versus a stale security-adjacent cache on
    a miss.
    """
    if method != "on_update":
        return
    try:
        from verenigingen.utils.security.api_security_framework import APISecurityFramework

        APISecurityFramework.invalidate_user_role_cache(doc.name)
        frappe.logger("verenigingen.cache_invalidation").info(
            f"User role cache invalidated for {doc.name} on User save"
        )
    except Exception as e:
        # Don't fail the user save if cache invalidation fails
        frappe.logger("verenigingen.cache_invalidation").error(
            f"Failed to invalidate user role cache for {doc.name}: {str(e)}"
        )


def invalidate_all_user_caches_on_role_profile_update(doc, method):
    """
    Hook for Role Profile doctype: Invalidate all user role caches when role profile changes

    This is a broader invalidation since we don't know which users have this role profile.
    """
    if method in ["on_update", "after_insert", "on_trash"]:
        try:
            from verenigingen.utils.security.api_security_framework import APISecurityFramework

            # Nuclear option: invalidate all user role caches since role profiles affect multiple users
            APISecurityFramework.invalidate_user_role_cache()  # No user specified = all users
            frappe.logger("verenigingen.cache_invalidation").info(
                f"All user role caches invalidated due to Role Profile '{doc.name}' change"
            )
        except Exception as e:
            # Don't fail the role profile save if cache invalidation fails
            frappe.logger("verenigingen.cache_invalidation").error(
                f"Failed to invalidate all user role caches for Role Profile {doc.name}: {str(e)}"
            )


def invalidate_user_cache_on_user_role_update(doc, method):
    """
    Hook for Has Role doctype (User's individual role assignments)

    This handles direct role assignments to users (not via role profiles).
    """
    if method in ["on_update", "after_insert", "on_trash"]:
        try:
            from verenigingen.utils.security.api_security_framework import APISecurityFramework

            # Get the user from the parent (User doctype)
            if doc.parent and doc.parenttype == "User":
                APISecurityFramework.invalidate_user_role_cache(doc.parent)
                frappe.logger("verenigingen.cache_invalidation").info(
                    f"User role cache invalidated for {doc.parent} due to individual role change"
                )
        except Exception as e:
            # Don't fail the role assignment if cache invalidation fails
            frappe.logger("verenigingen.cache_invalidation").error(
                f"Failed to invalidate user role cache for role assignment: {str(e)}"
            )


def clear_security_caches_on_migrate():
    """
    Clear all security-related caches during system migration

    This ensures fresh data after system updates.
    """
    try:
        from verenigingen.utils.security.api_security_framework import APISecurityFramework

        APISecurityFramework.invalidate_user_role_cache()  # Clear all user role caches

        # Also clear critical operation caches
        import redis

        redis_client = frappe.cache.redis_client
        op_pattern = "critical_op_check:*"
        op_keys = redis_client.keys(op_pattern)
        if op_keys:
            redis_client.delete(*op_keys)
            frappe.logger("verenigingen.cache_invalidation").info(
                f"Cleared {len(op_keys)} critical operation cache entries during migration"
            )

    except Exception as e:
        frappe.logger("verenigingen.cache_invalidation").error(
            f"Failed to clear security caches during migration: {str(e)}"
        )
