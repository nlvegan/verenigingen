# Webhook User Setup for Verenigingen App
# Creates and configures a secure webhook user during app installation

import secrets
import string

import frappe


def setup_webhook_user():
    """
    Create and configure a dedicated webhook user with minimal required permissions.

    This function creates a secure webhook user account during app installation to ensure
    production deployments have proper security from day one without manual configuration.

    Returns:
        dict: Status and details of the webhook user setup
    """
    try:
        print("🔐 Setting up secure webhook user...")

        # Generate secure webhook user credentials
        webhook_user_email = generate_webhook_user_email()
        webhook_password = generate_secure_password()

        # Create the webhook user account
        user_result = create_webhook_user_account(webhook_user_email, webhook_password)
        if not user_result["success"]:
            return user_result

        # Assign the webhook role and role profile
        role_result = assign_webhook_roles(webhook_user_email)
        if not role_result["success"]:
            return role_result

        # Configure the webhook user in Verenigingen Payments Settings
        config_result = configure_webhook_user_in_settings(webhook_user_email)
        if not config_result["success"]:
            return config_result

        print(f"✅ Webhook user setup completed successfully")
        print(f"   📧 User: {webhook_user_email}")
        print(f"   🔐 Password: {webhook_password}")
        print(f"   🛡️ Role: Verenigingen Webhook User")
        print(f"   ⚙️ Configured in Verenigingen Payments Settings")

        return {
            "success": True,
            "webhook_user_email": webhook_user_email,
            "webhook_password": webhook_password,
            "message": "Webhook user created and configured successfully",
        }

    except Exception as e:
        error_msg = f"Failed to setup webhook user: {str(e)}"
        frappe.logger().error(error_msg)
        print(f"❌ {error_msg}")
        return {"success": False, "message": error_msg}


def generate_webhook_user_email():
    """Generate a unique webhook user email based on site name"""
    try:
        site_name = frappe.conf.site_name or frappe.local.site
        # Clean the site name for email usage
        clean_site = site_name.replace(".", "-").replace("_", "-")
        webhook_email = f"webhook-user@{clean_site}"

        # Ensure uniqueness by adding suffix if needed
        counter = 1
        original_email = webhook_email
        while frappe.db.exists("User", webhook_email):
            webhook_email = f"webhook-user-{counter}@{clean_site}"
            counter += 1

        return webhook_email

    except Exception:
        # Fallback to a generic webhook user email
        counter = 1
        webhook_email = f"webhook-user@verenigingen-app.local"
        while frappe.db.exists("User", webhook_email):
            webhook_email = f"webhook-user-{counter}@verenigingen-app.local"
            counter += 1
        return webhook_email


def generate_secure_password(length=16):
    """Generate a cryptographically secure password"""
    # Use a mix of letters, numbers, and safe special characters
    alphabet = string.ascii_letters + string.digits + "!@#$%&*+-=?"
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    return password


def create_webhook_user_account(webhook_email, webhook_password):
    """Create the webhook user account with proper security settings"""
    try:
        if frappe.db.exists("User", webhook_email):
            print(f"   ℹ️ Webhook user {webhook_email} already exists")
            return {"success": True, "message": "Webhook user already exists"}

        # Create user with minimal privileges
        user_doc = frappe.get_doc(
            {
                "doctype": "User",
                "email": webhook_email,
                "first_name": "Webhook",
                "last_name": "User",
                "full_name": "Webhook User",
                "enabled": 1,
                "user_type": "System User",
                "new_password": webhook_password,
                "send_welcome_email": 0,  # Don't send welcome email
                "roles": [{"role": "Verenigingen Webhook User"}],
            }
        )

        user_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        print(f"   ✅ Created webhook user: {webhook_email}")
        return {"success": True, "message": f"Webhook user {webhook_email} created"}

    except Exception as e:
        error_msg = f"Failed to create webhook user account: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def assign_webhook_roles(webhook_email):
    """Assign the webhook role and role profile to the user"""
    try:
        user_doc = frappe.get_doc("User", webhook_email)

        # Check if user already has the webhook role
        has_webhook_role = any(role.role == "Verenigingen Webhook User" for role in user_doc.roles)

        if not has_webhook_role:
            # Add the webhook role
            user_doc.append("roles", {"role": "Verenigingen Webhook User"})

        # Set the role profile
        user_doc.role_profile_name = "Verenigingen Webhook User"
        user_doc.module_profile = "Verenigingen Webhook User"

        user_doc.save(ignore_permissions=True)
        frappe.db.commit()

        print(f"   ✅ Assigned webhook role and profiles to {webhook_email}")
        return {"success": True, "message": "Webhook roles assigned"}

    except Exception as e:
        error_msg = f"Failed to assign webhook roles: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def configure_webhook_user_in_settings(webhook_email):
    """Configure the webhook user in Verenigingen Payments Settings"""
    try:
        # Get or create the payments settings
        if not frappe.db.exists("Verenigingen Payments Settings", "Verenigingen Payments Settings"):
            settings_doc = frappe.get_doc({"doctype": "Verenigingen Payments Settings"})
            settings_doc.insert(ignore_permissions=True)
        else:
            settings_doc = frappe.get_doc("Verenigingen Payments Settings", "Verenigingen Payments Settings")

        # Set the webhook user
        settings_doc.webhook_user = webhook_email
        settings_doc.save(ignore_permissions=True)
        frappe.db.commit()

        print(f"   ✅ Configured {webhook_email} in Verenigingen Payments Settings")
        return {"success": True, "message": "Webhook user configured in settings"}

    except Exception as e:
        error_msg = f"Failed to configure webhook user in settings: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def verify_webhook_user_setup():
    """
    Verify that the webhook user is properly set up and configured.

    Returns:
        dict: Verification results showing setup status
    """
    try:
        print("🔍 Verifying webhook user setup...")

        verification = {
            "settings_exist": False,
            "webhook_user_configured": False,
            "webhook_user_exists": False,
            "webhook_user_has_role": False,
            "webhook_user_has_profile": False,
            "setup_complete": False,
        }

        # Check if Verenigingen Payments Settings exists
        if frappe.db.exists("Verenigingen Payments Settings", "Verenigingen Payments Settings"):
            verification["settings_exist"] = True

            # Check if webhook user is configured
            settings = frappe.get_doc("Verenigingen Payments Settings", "Verenigingen Payments Settings")
            webhook_user = getattr(settings, "webhook_user", None)

            if webhook_user:
                verification["webhook_user_configured"] = True

                # Check if webhook user exists
                if frappe.db.exists("User", webhook_user):
                    verification["webhook_user_exists"] = True

                    # Check if user has proper role
                    user_doc = frappe.get_doc("User", webhook_user)
                    has_role = any(role.role == "Verenigingen Webhook User" for role in user_doc.roles)
                    verification["webhook_user_has_role"] = has_role

                    # Check if user has proper role profile
                    has_profile = user_doc.role_profile_name == "Verenigingen Webhook User"
                    verification["webhook_user_has_profile"] = has_profile

                    verification["webhook_user_email"] = webhook_user

        # Determine if setup is complete
        verification["setup_complete"] = (
            verification["settings_exist"]
            and verification["webhook_user_configured"]
            and verification["webhook_user_exists"]
            and verification["webhook_user_has_role"]
            and verification["webhook_user_has_profile"]
        )

        status = "✅ Complete" if verification["setup_complete"] else "❌ Incomplete"
        print(f"   🔍 Webhook user setup verification: {status}")

        return {
            "success": True,
            "verification": verification,
            "setup_complete": verification["setup_complete"],
        }

    except Exception as e:
        error_msg = f"Failed to verify webhook user setup: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


@frappe.whitelist()
def setup_webhook_user_manual():
    """Manual API endpoint to setup webhook user (for development/troubleshooting)"""
    try:
        result = setup_webhook_user()
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def verify_webhook_user_setup_manual():
    """Manual API endpoint to verify webhook user setup"""
    try:
        result = verify_webhook_user_setup()
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


def get_webhook_credentials_for_display():
    """
    Get webhook user credentials for display in setup instructions.

    Note: This only returns the email, not the password for security reasons.
    The password is only shown during initial setup.

    Returns:
        dict: Webhook user information for display
    """
    try:
        if not frappe.db.exists("Verenigingen Payments Settings", "Verenigingen Payments Settings"):
            return {"success": False, "message": "Verenigingen Payments Settings not configured"}

        settings = frappe.get_doc("Verenigingen Payments Settings", "Verenigingen Payments Settings")
        webhook_user = getattr(settings, "webhook_user", None)

        if not webhook_user:
            return {"success": False, "message": "No webhook user configured"}

        if not frappe.db.exists("User", webhook_user):
            return {"success": False, "message": "Configured webhook user does not exist"}

        return {
            "success": True,
            "webhook_user_email": webhook_user,
            "message": "Webhook user is configured and active",
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_webhook_credentials_manual():
    """Manual API endpoint to get webhook credentials for display"""
    try:
        result = get_webhook_credentials_for_display()
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}
