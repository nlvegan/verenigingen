"""
Firefox Session Cache Corruption Fix

Fixes Firefox-specific session cache corruption that causes "User None is disabled" errors.
The issue occurs when Firefox's session cache becomes inconsistent while the database
session remains valid. This fix detects and clears corrupted cache entries.
"""

import frappe
from frappe.sessions import Session


def apply_firefox_cache_fix():
    """Apply fix for Firefox session cache corruption"""

    # Store original validate_user
    _original_validate_user = Session.validate_user

    def safe_validate_user(self):
        """Validate user with Firefox cache corruption detection"""
        try:
            return _original_validate_user(self)
        except frappe.ValidationError as e:
            if "User None is disabled" in str(e):
                # This is the Firefox cache corruption - clear this session's cache
                frappe.logger().warning(
                    f"Firefox cache corruption detected for session {self.sid}, clearing cache"
                )
                frappe.cache.hdel("session", self.sid)

                # Reload session from database
                self.resume()
                return
            # Re-raise other validation errors
            raise

    # Apply the patch
    Session.validate_user = safe_validate_user
    frappe.logger().info("Applied Firefox session cache corruption fix")


# Auto-apply the fix when imported
apply_firefox_cache_fix()
