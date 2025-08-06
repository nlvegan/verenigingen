#!/usr/bin/env python3
"""
Temporary fix for role profile migration lock issues
"""
import frappe


def disable_role_profile_queue():
    """Temporarily disable role profile background queue to allow migration"""
    # Monkey patch the queue_action method to skip queuing
    from frappe.core.doctype.role_profile.role_profile import RoleProfile

    # Store original method
    if not hasattr(RoleProfile, "_original_queue_action"):
        RoleProfile._original_queue_action = RoleProfile.queue_action

    # Override with no-op
    def skip_queue_action(self, action=None, doc=None, **kwargs):
        print(f"Skipping queue action for role profile: {self.name}")
        return

    RoleProfile.queue_action = skip_queue_action
    print("Disabled role profile queue actions for migration")


def restore_role_profile_queue():
    """Restore original role profile queue behavior"""
    from frappe.core.doctype.role_profile.role_profile import RoleProfile

    if hasattr(RoleProfile, "_original_queue_action"):
        RoleProfile.queue_action = RoleProfile._original_queue_action
        delattr(RoleProfile, "_original_queue_action")
        print("Restored role profile queue actions")


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("Applying role profile queue fix...")
    disable_role_profile_queue()

    frappe.destroy()
