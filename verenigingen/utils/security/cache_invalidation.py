"""
Security Framework Cache Invalidation Hooks

Handles intelligent cache invalidation for the security framework when user roles
or role profiles are updated, ensuring cached security data stays fresh without
compromising performance.
"""

import frappe


def invalidate_user_role_cache_on_user_update(doc, method):
    """
    Hook for User doctype: Invalidate role cache when user's role_profile_name changes

    This hook is triggered on User save/update operations.
    """
    if method in ["on_update", "after_insert"]:
        try:
            from verenigingen.utils.security.api_security_framework import APISecurityFramework

            # Check if role_profile_name field was changed
            if doc.has_value_changed("role_profile_name") or method == "after_insert":
                APISecurityFramework.invalidate_user_role_cache(doc.name)
                frappe.logger("verenigingen.cache_invalidation").info(
                    f"User role cache invalidated for {doc.name} due to role profile change"
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
