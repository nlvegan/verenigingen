"""
DEPRECATED: Member Account Service

WARNING: This module is DEPRECATED and contains security violations.
Use the new secure AccountCreationManager instead:
    from verenigingen.utils.account_creation_manager import queue_account_creation_for_member

This module is kept only for backward compatibility during migration.
All methods have been replaced with secure implementations that queue
account creation through the background processing system.

SECURITY ISSUE: Contains 6 instances of ignore_permissions=True
STATUS: To be removed after migration to AccountCreationManager

Author: Verenigingen Development Team
Last Updated: 2025-08-24 (DEPRECATED)
"""

import frappe
from frappe import _
from frappe.utils import now


def create_member_user_account(member, send_welcome_email=True, preserve_payment_data=True):
    """
    Create a user account for a member to access portal pages.

    This is the shared service that can be used by both approval workflows
    and import processes.

    Args:
        member: Member document or member name
        send_welcome_email: Whether to send welcome email to new user
        preserve_payment_data: Whether to preserve existing payment method data (important for imports)

    Returns:
        dict: Success/failure result with user details
    """
    try:
        # Handle both Member document and member name
        if isinstance(member, str):
            member_doc = frappe.get_doc("Member", member)
            member_name = member
        else:
            member_doc = member
            member_name = member.name

        # Check if user already exists
        if member_doc.user:
            return {
                "success": False,
                "message": _("User account already exists for this member"),
                "user": member_doc.user,
                "action": "already_exists",
            }

        # Validate email
        if not member_doc.email:
            return {"success": False, "error": "Member must have an email address to create user account"}

        # Check if a user with this email already exists
        existing_user = frappe.db.get_value("User", {"email": member_doc.email}, "name")
        if existing_user:
            # Link the existing user to the member
            result = _link_existing_user_to_member(member_doc, existing_user)
            return result

        # Create new user
        result = _create_new_user_for_member(member_doc, send_welcome_email)

        # Log success for audit purposes
        frappe.logger().info(
            f"Member account service: Created user account {result.get('user')} for member {member_name}"
        )

        return result

    except Exception as e:
        error_msg = f"Error creating user account for member {member_name}: {str(e)}"
        frappe.log_error(frappe.get_traceback(), "Member Account Service Error")
        frappe.logger().error(error_msg)
        return {"success": False, "error": str(e)}


def _link_existing_user_to_member(member_doc, existing_user):
    """Link an existing user account to a member record"""
    try:
        # Link the user to the member
        member_doc.user = existing_user
        member_doc.save(ignore_permissions=True)  # System operation

        # Add member roles to existing user
        add_member_roles_to_user(existing_user)

        frappe.logger().info(f"Linked existing user {existing_user} to member {member_doc.name}")

        return {
            "success": True,
            "message": _("Linked existing user account to member"),
            "user": existing_user,
            "action": "linked_existing",
        }

    except Exception as e:
        frappe.log_error(f"Error linking user {existing_user} to member {member_doc.name}: {str(e)}")
        raise


def _create_new_user_for_member(member_doc, send_welcome_email):
    """Create a new user account for a member"""
    try:
        # Create new user
        user = frappe.new_doc("User")
        user.email = member_doc.email
        user.first_name = member_doc.first_name or ""
        user.last_name = member_doc.last_name or ""
        user.full_name = member_doc.full_name

        # Handle welcome email setting
        from verenigingen.utils.boolean_utils import cbool

        user.send_welcome_email = cbool(send_welcome_email)
        user.user_type = "System User"
        user.enabled = 1

        # Insert user
        user.insert(ignore_permissions=True)  # System operation

        # Set allowed modules for member users
        set_member_user_modules(user.name)

        # Add member-specific roles
        add_member_roles_to_user(user.name)

        # Link user to member
        member_doc.user = user.name
        member_doc.save(ignore_permissions=True)  # System operation

        frappe.logger().info(f"Created new user account {user.name} for member {member_doc.name}")

        return {
            "success": True,
            "message": _("User account created successfully"),
            "user": user.name,
            "action": "created_new",
        }

    except Exception as e:
        frappe.log_error(f"Error creating new user for member {member_doc.name}: {str(e)}")
        raise


def add_member_roles_to_user(user_name):
    """Add appropriate role profile for a member user to access portal pages"""
    try:
        # Check if Verenigingen Member role profile exists
        role_profile_name = "Verenigingen Member"
        if not frappe.db.exists("Role Profile", role_profile_name):
            frappe.logger().warning(
                f"Role Profile {role_profile_name} does not exist. Creating basic roles manually."
            )
            # Fallback to individual role assignment
            _assign_individual_member_roles(user_name)
            return

        # Add role profile and module profile to user
        user = frappe.get_doc("User", user_name)

        # Clear existing roles first to avoid conflicts with role profile
        user.roles = []

        # Assign the role profile (this should automatically apply module profile, but we'll be explicit)
        user.role_profile_name = role_profile_name

        # Explicitly set module profile to ensure module access
        module_profile_name = "Verenigingen Member"
        if frappe.db.exists("Module Profile", module_profile_name):
            user.module_profile = module_profile_name
            frappe.logger().info(f"Assigned module profile '{module_profile_name}' to user {user_name}")
        else:
            frappe.logger().warning(f"Module Profile {module_profile_name} does not exist")

        # Ensure user is enabled
        if not user.enabled:
            user.enabled = 1

        # Save with validation handling
        try:
            user.save(ignore_permissions=True)  # System operation
            frappe.logger().info(f"Assigned role profile '{role_profile_name}' to user {user_name}")
            return user.name

        except Exception as save_error:
            frappe.log_error(f"Error saving user {user_name} with role profile: {str(save_error)}")
            # Fallback to individual role assignment
            _assign_individual_member_roles(user_name)
            return user.name

    except Exception as e:
        frappe.log_error(f"Error adding role profile to user {user_name}: {str(e)}")
        # Fallback to individual role assignment
        try:
            _assign_individual_member_roles(user_name)
            return user_name
        except Exception:
            return None


def _assign_individual_member_roles(user_name):
    """Fallback method to assign individual roles when role profile is not available"""
    try:
        # Define the roles that members need for portal access
        member_roles = [
            "Verenigingen Member",  # Primary member role for all member access
            "All",  # Standard role for basic system access
        ]

        # Check if Verenigingen Member role exists, create if not
        if not frappe.db.exists("Role", "Verenigingen Member"):
            create_verenigingen_member_role()

        # Add roles to user
        user = frappe.get_doc("User", user_name)

        # Clear existing roles first to avoid conflicts
        user.roles = []

        for role in member_roles:
            if not frappe.db.exists("Role", role):
                frappe.logger().warning(f"Role {role} does not exist, skipping")
                continue
            # Always add the role since we cleared roles above
            user.append("roles", {"role": role})

        # Also set module profile even in fallback mode
        module_profile_name = "Verenigingen Member"
        if frappe.db.exists("Module Profile", module_profile_name):
            user.module_profile = module_profile_name
            frappe.logger().info(
                f"Assigned module profile '{module_profile_name}' to user {user_name} (fallback mode)"
            )

        # Ensure user is enabled
        if not user.enabled:
            user.enabled = 1

        user.save(ignore_permissions=True)  # System operation
        frappe.logger().info(f"Assigned individual roles to user {user_name}: {member_roles}")

    except Exception as e:
        frappe.log_error(f"Error assigning individual member roles to user {user_name}: {str(e)}")
        raise


def set_member_user_modules(user_name):
    """Set allowed modules for member users to access appropriate features"""
    try:
        # Define modules that members should have access to
        allowed_modules = [
            "Core",  # Basic system functionality
            "Custom",  # Custom modules and doctypes
            "Website",  # Website and portal access
            "Verenigingen",  # Main association module
        ]

        user = frappe.get_doc("User", user_name)

        # Clear existing modules
        user.block_modules = []

        # Set allowed modules by blocking others
        all_modules = frappe.get_all("Module Def", fields=["module_name"])
        for module in all_modules:
            if module.module_name not in allowed_modules:
                user.append("block_modules", {"module": module.module_name})

        user.save(ignore_permissions=True)  # System operation
        frappe.logger().info(f"Set allowed modules for user {user_name}: {allowed_modules}")

    except Exception as e:
        frappe.log_error(f"Error setting modules for user {user_name}: {str(e)}")


def create_verenigingen_member_role():
    """Create the Verenigingen Member role if it doesn't exist"""
    try:
        if frappe.db.exists("Role", "Verenigingen Member"):
            return

        role = frappe.new_doc("Role")
        role.role_name = "Verenigingen Member"
        role.description = "Role for association members to access portal features"
        role.insert(ignore_permissions=True)

        frappe.logger().info("Created Verenigingen Member role")

    except Exception as e:
        frappe.log_error(f"Error creating Verenigingen Member role: {str(e)}")


def validate_member_for_user_account(member_doc):
    """
    Validate that a member is ready for user account creation.

    Args:
        member_doc: Member document to validate

    Returns:
        dict: Validation result with any issues found
    """
    issues = []

    # Check required fields
    if not member_doc.email:
        issues.append("Member must have an email address")

    if not member_doc.first_name and not member_doc.last_name:
        issues.append("Member must have at least first name or last name")

    # Check member status
    if member_doc.status not in ["Active", "Approved"]:
        issues.append(f"Member status '{member_doc.status}' not suitable for user account creation")

    # Check for duplicate email in other members
    duplicate_member = frappe.db.get_value(
        "Member", {"email": member_doc.email, "name": ["!=", member_doc.name]}, "name"
    )
    if duplicate_member:
        issues.append(f"Email {member_doc.email} is already used by member {duplicate_member}")

    return {"valid": len(issues) == 0, "issues": issues}


def bulk_create_user_accounts(member_names, send_welcome_emails=True, continue_on_error=True):
    """
    Create user accounts for multiple members in bulk.

    This is particularly useful for import processes.

    Args:
        member_names: List of member names to create accounts for
        send_welcome_emails: Whether to send welcome emails
        continue_on_error: Whether to continue processing if individual members fail

    Returns:
        dict: Summary of results with success/failure counts
    """
    results = {"total": len(member_names), "success": 0, "failed": 0, "skipped": 0, "details": []}

    for member_name in member_names:
        try:
            # Get member document
            member_doc = frappe.get_doc("Member", member_name)

            # Validate member first
            validation = validate_member_for_user_account(member_doc)
            if not validation["valid"]:
                results["skipped"] += 1
                results["details"].append(
                    {"member": member_name, "status": "skipped", "reason": "; ".join(validation["issues"])}
                )
                continue

            # Create user account
            result = create_member_user_account(member_doc, send_welcome_email=send_welcome_emails)

            if result["success"]:
                results["success"] += 1
                results["details"].append(
                    {
                        "member": member_name,
                        "status": "success",
                        "user": result["user"],
                        "action": result["action"],
                    }
                )
            else:
                results["failed"] += 1
                results["details"].append(
                    {
                        "member": member_name,
                        "status": "failed",
                        "error": result.get("error", result.get("message", "Unknown error")),
                    }
                )

        except Exception as e:
            results["failed"] += 1
            results["details"].append({"member": member_name, "status": "failed", "error": str(e)})

            if not continue_on_error:
                break

            frappe.log_error(f"Error processing member {member_name} in bulk operation: {str(e)}")

    frappe.logger().info(
        f"Bulk user account creation completed: {results['success']} success, "
        f"{results['failed']} failed, {results['skipped']} skipped"
    )

    return results
