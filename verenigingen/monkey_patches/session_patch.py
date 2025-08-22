"""
Monkey patch for Frappe's session handling to prevent "User None is disabled" errors

This patch intercepts session resumption to validate user data before it causes errors.
The issue occurs when cached session data contains None or invalid user values.
"""

import frappe
from frappe.sessions import Session


# Store the original resume method
_original_resume = Session.resume


def patched_resume(self):
    """
    Patched resume method that validates user data before resuming session
    
    This prevents "User None is disabled" errors that occur when cached
    session data contains corrupted user values.
    """
    try:
        # Call the original method to get session data
        _original_resume(self)
        
    except frappe.ValidationError as e:
        # Check if it's the specific "User None is disabled" error
        if "User None is disabled" in str(e):
            frappe.logger().warning(
                f"Session resume failed with None user. Session ID: {getattr(self, 'sid', 'unknown')}. "
                f"Falling back to Guest session."
            )
            
            # Clear the corrupted session data
            if hasattr(self, 'sid') and self.sid:
                try:
                    # Clear from cache
                    frappe.cache().delete(f"sess:{self.sid}")
                    # Clear from database
                    frappe.db.sql("DELETE FROM tabSessions WHERE sid = %s", self.sid)
                    frappe.db.commit()
                except:
                    pass  # Don't let cleanup failures break the flow
            
            # Start as guest instead of crashing
            self.start_as_guest()
        else:
            # Re-raise other validation errors
            raise


def patched_get_session_record(self):
    """
    Patched method to validate session data before using it
    
    This adds defensive validation to prevent None user values from
    being loaded from cached or database session data.
    """
    from frappe.auth import clear_cookies
    
    # Get the session data
    r = self.get_session_data()
    
    if r:
        # Validate the user field before using it
        user = getattr(r, 'user', None)
        
        # Check for corrupted user values
        if user is None or user == 'None' or user == '' or not isinstance(user, str):
            frappe.logger().warning(
                f"Corrupted session data detected. User value: {repr(user)}. "
                f"Session ID: {self.sid}. Clearing session."
            )
            
            # Clear the corrupted session
            if self.sid:
                try:
                    frappe.cache().delete(f"sess:{self.sid}")
                    frappe.db.sql("DELETE FROM tabSessions WHERE sid = %s", self.sid)
                    frappe.db.commit()
                except:
                    pass
            
            # Return None to trigger guest session
            return None
    
    return r


# Store original get_session_record method
_original_get_session_record = Session.get_session_record


def apply_session_patches():
    """Apply the monkey patches to Session class"""
    
    # Only patch if not already patched
    if Session.resume != patched_resume:
        Session.resume = patched_resume
        frappe.logger().info("Applied session resume patch to prevent 'User None is disabled' errors")
    
    if Session.get_session_record != patched_get_session_record:
        Session.get_session_record = patched_get_session_record
        frappe.logger().info("Applied session record validation patch")


def remove_session_patches():
    """Remove the monkey patches (for testing/debugging)"""
    
    Session.resume = _original_resume
    Session.get_session_record = _original_get_session_record
    frappe.logger().info("Removed session patches")