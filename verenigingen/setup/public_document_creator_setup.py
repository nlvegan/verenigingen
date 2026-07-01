# Public Document Creator User Setup for Verenigingen App
# Creates and configures a secure system user for public-facing document creation
# (donations, member applications, etc.)

import secrets
import string

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

# Role name constant
PUBLIC_CREATOR_ROLE = "Verenigingen Public Document Creator"


def setup_public_document_creator():
    """
    Create and configure a dedicated system user for public document creation.

    This user replaces direct Administrator escalation for public-facing flows like:
    - Donation processing (creating Donor and Donation records)
    - Member application submission (creating Member records)
    - Address creation for public forms

    The user has minimal permissions - only what's needed for these operations.

    Returns:
        dict: Status and details of the setup
    """
    try:
        print("🔐 Setting up public document creator user...")

        # Ensure the role exists first
        role_result = ensure_public_creator_role_exists()
        if not role_result["success"]:
            return role_result

        # Generate secure credentials
        user_email = generate_public_creator_email()
        user_password = generate_secure_password()

        # Create the user account
        user_result = create_public_creator_account(user_email, user_password)
        if not user_result["success"]:
            return user_result

        # Assign roles
        role_result = assign_public_creator_roles(user_email)
        if not role_result["success"]:
            return role_result

        # Configure in Verenigingen Settings as creation_user
        config_result = configure_creation_user_in_settings(user_email)
        if not config_result["success"]:
            return config_result

        print("✅ Public document creator setup completed successfully")
        print(f"   📧 User: {user_email}")
        print(f"   🔐 Password: {user_password}")
        print(f"   🛡️ Role: {PUBLIC_CREATOR_ROLE}")
        print("   ⚙️ Configured as creation_user in Verenigingen Settings")

        return {
            "success": True,
            "user_email": user_email,
            "user_password": user_password,
            "message": "Public document creator setup completed successfully",
        }

    except Exception as e:
        error_msg = f"Failed to setup public document creator: {str(e)}"
        frappe.logger().error(error_msg)
        print(f"❌ {error_msg}")
        return {"success": False, "message": error_msg}


def ensure_public_creator_role_exists():
    """Ensure the public document creator role exists with proper permissions"""
    try:
        if frappe.db.exists("Role", PUBLIC_CREATOR_ROLE):
            print(f"   ℹ️ Role {PUBLIC_CREATOR_ROLE} already exists")
            return {"success": True, "message": "Role already exists"}

        # Create the role
        role_doc = frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": PUBLIC_CREATOR_ROLE,
                "desk_access": 0,  # No desk access needed
                "is_custom": 1,
                "disabled": 0,
            }
        )
        role_doc.insert(ignore_permissions=True)

        # Set up minimal permissions for the role.
        #
        # NOTE: the target doctype for each permission is keyed as "parent" (the
        # Custom DocPerm field that links to the DocType), NOT "doctype". Using
        # "doctype" here would collide with the "doctype": "Custom DocPerm" key in
        # frappe.get_doc({...}) below (dict spread lets the later key win), which
        # would attempt to insert a Donor/Donation/etc. document with permission
        # fields instead of a Custom DocPerm row.
        managed_doctypes = ["Donor", "Donation", "Member", "Address", "Contact"]
        permissions_to_create = [
            {
                "parent": doctype,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": PUBLIC_CREATOR_ROLE,
                "permlevel": 0,
                "read": 1,
                "write": 1,
                "create": 1,
                "delete": 0,
                "submit": 0,
                "cancel": 0,
            }
            for doctype in managed_doctypes
        ]

        for perm in permissions_to_create:
            # Check if permission already exists
            existing = frappe.db.exists(
                "Custom DocPerm",
                {"parent": perm["parent"], "role": perm["role"], "permlevel": perm["permlevel"]},
            )
            if not existing:
                perm_doc = frappe.get_doc({"doctype": "Custom DocPerm", **perm})
                perm_doc.insert(ignore_permissions=True)

        frappe.db.commit()
        print(f"   ✅ Created role {PUBLIC_CREATOR_ROLE} with minimal permissions")
        return {"success": True, "message": f"Role {PUBLIC_CREATOR_ROLE} created"}

    except Exception as e:
        error_msg = f"Failed to create role: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def generate_public_creator_email():
    """Generate a unique email for the public document creator user"""
    try:
        site_name = frappe.conf.site_name or frappe.local.site
        # Keep the dots: a Frappe site name is an FQDN, which is already a valid
        # email domain. Replacing "." with "-" produced a dotless domain (e.g.
        # "veg11-veganisme-org") that Frappe rejects as an invalid email address,
        # making user creation — and thus the whole setup — fail. Only underscores
        # (illegal in a hostname) need sanitising.
        clean_site = site_name.replace("_", "-")
        user_email = f"public-creator@{clean_site}"

        counter = 1
        while frappe.db.exists("User", user_email):
            user_email = f"public-creator-{counter}@{clean_site}"
            counter += 1

        return user_email

    except Exception:
        counter = 1
        user_email = "public-creator@verenigingen-app.local"
        while frappe.db.exists("User", user_email):
            user_email = f"public-creator-{counter}@verenigingen-app.local"
            counter += 1
        return user_email


def generate_secure_password(length=16):
    """Generate a cryptographically secure password"""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*+-=?"
    password = "".join(secrets.choice(alphabet) for _ in range(length))
    return password


def create_public_creator_account(user_email, user_password):
    """Create the public document creator user account"""
    try:
        if frappe.db.exists("User", user_email):
            print(f"   ℹ️ User {user_email} already exists")
            return {"success": True, "message": "User already exists"}

        user_doc = frappe.get_doc(
            {
                "doctype": "User",
                "email": user_email,
                "first_name": "Public Document",
                "last_name": "Creator",
                "full_name": "Public Document Creator",
                "enabled": 1,
                "user_type": "System User",
                "new_password": user_password,
                "send_welcome_email": 0,
                "roles": [{"role": PUBLIC_CREATOR_ROLE}],
            }
        )

        user_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        print(f"   ✅ Created user: {user_email}")
        return {"success": True, "message": f"User {user_email} created"}

    except Exception as e:
        error_msg = f"Failed to create user account: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def assign_public_creator_roles(user_email):
    """Assign the public creator role to the user"""
    try:
        user_doc = frappe.get_doc("User", user_email)

        has_role = any(role.role == PUBLIC_CREATOR_ROLE for role in user_doc.roles)
        if not has_role:
            user_doc.append("roles", {"role": PUBLIC_CREATOR_ROLE})
            user_doc.save(ignore_permissions=True)
            frappe.db.commit()

        print(f"   ✅ Assigned role {PUBLIC_CREATOR_ROLE} to {user_email}")
        return {"success": True, "message": "Role assigned"}

    except Exception as e:
        error_msg = f"Failed to assign role: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def configure_creation_user_in_settings(user_email):
    """Configure the user as creation_user in Verenigingen Settings"""
    try:
        settings_name = "Verenigingen Settings"
        if not frappe.db.exists("Verenigingen Settings", settings_name):
            print("   ⚠️ Verenigingen Settings not found, skipping configuration")
            return {"success": True, "message": "Settings not found, skipped"}

        settings = frappe.get_doc("Verenigingen Settings", settings_name)
        settings.creation_user = user_email
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        print(f"   ✅ Configured {user_email} as creation_user in Verenigingen Settings")
        return {"success": True, "message": "creation_user configured in settings"}

    except Exception as e:
        error_msg = f"Failed to configure settings: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def verify_role_permissions():
    """
    Verify that the public document creator role has the required permissions.

    Returns:
        dict: Permission verification results with details
    """
    required_permissions = {
        "Donor": ["read", "write", "create"],
        "Donation": ["read", "write", "create"],
        "Member": ["read", "write", "create"],
        "Address": ["read", "write", "create"],
        "Contact": ["read", "write", "create"],
    }

    results = {
        "all_permissions_valid": True,
        "permissions": {},
        "missing_permissions": [],
    }

    for doctype, required_perms in required_permissions.items():
        doctype_result = {
            "exists": frappe.db.exists("DocType", doctype),
            "required": required_perms,
            "granted": [],
            "missing": [],
        }

        if doctype_result["exists"]:
            # Check Custom DocPerm for our role
            for perm_type in required_perms:
                has_perm = frappe.db.exists(
                    "Custom DocPerm",
                    {
                        "parent": doctype,
                        "role": PUBLIC_CREATOR_ROLE,
                        perm_type: 1,
                    },
                )
                if has_perm:
                    doctype_result["granted"].append(perm_type)
                else:
                    doctype_result["missing"].append(perm_type)
                    results["missing_permissions"].append(f"{doctype}:{perm_type}")

        results["permissions"][doctype] = doctype_result

    results["all_permissions_valid"] = len(results["missing_permissions"]) == 0
    return results


def verify_public_document_creator_setup():
    """
    Verify that the public document creator is properly set up.

    Checks:
    1. Role exists
    2. Settings configured
    3. User exists and has role
    4. Required permissions are granted

    Returns:
        dict: Verification results
    """
    try:
        print("🔍 Verifying public document creator setup...")

        verification = {
            "role_exists": False,
            "settings_exist": False,
            "creation_user_configured": False,
            "creation_user_exists": False,
            "creation_user_has_role": False,
            "permissions_valid": False,
            "setup_complete": False,
        }

        # Check role exists
        if frappe.db.exists("Role", PUBLIC_CREATOR_ROLE):
            verification["role_exists"] = True
            print(f"   ✅ Role {PUBLIC_CREATOR_ROLE} exists")

            # Verify permissions for the role
            perm_results = verify_role_permissions()
            verification["permissions_valid"] = perm_results["all_permissions_valid"]
            verification["permission_details"] = perm_results

            if perm_results["all_permissions_valid"]:
                print("   ✅ All required permissions configured")
            else:
                print(f"   ⚠️ Missing permissions: {', '.join(perm_results['missing_permissions'])}")
        else:
            print(f"   ❌ Role {PUBLIC_CREATOR_ROLE} does not exist")

        # Check settings
        if frappe.db.exists("Verenigingen Settings", "Verenigingen Settings"):
            verification["settings_exist"] = True

            settings = frappe.get_doc("Verenigingen Settings", "Verenigingen Settings")
            creation_user = getattr(settings, "creation_user", None)

            if creation_user:
                verification["creation_user_configured"] = True
                print(f"   ✅ creation_user configured: {creation_user}")

                if frappe.db.exists("User", creation_user):
                    verification["creation_user_exists"] = True

                    user_doc = frappe.get_doc("User", creation_user)
                    has_role = any(role.role == PUBLIC_CREATOR_ROLE for role in user_doc.roles)
                    verification["creation_user_has_role"] = has_role

                    verification["creation_user_email"] = creation_user

                    if has_role:
                        print(f"   ✅ User has {PUBLIC_CREATOR_ROLE} role")
                    else:
                        print(f"   ⚠️ User missing {PUBLIC_CREATOR_ROLE} role")
                else:
                    print(f"   ❌ User {creation_user} does not exist")
            else:
                print("   ⚠️ creation_user not configured in settings")
        else:
            print("   ❌ Verenigingen Settings not found")

        # Determine if setup is complete (permissions are optional for backward compat)
        verification["setup_complete"] = (
            verification["role_exists"]
            and verification["settings_exist"]
            and verification["creation_user_configured"]
            and verification["creation_user_exists"]
        )

        # Full setup includes permissions
        verification["full_setup_complete"] = (
            verification["setup_complete"]
            and verification["permissions_valid"]
            and verification["creation_user_has_role"]
        )

        status = (
            "✅ Complete"
            if verification["full_setup_complete"]
            else ("⚠️ Partial" if verification["setup_complete"] else "❌ Incomplete")
        )
        print(f"   🔍 Public document creator setup verification: {status}")

        return {
            "success": True,
            "verification": verification,
            "setup_complete": verification["setup_complete"],
            "full_setup_complete": verification["full_setup_complete"],
        }

    except Exception as e:
        error_msg = f"Failed to verify setup: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def setup_public_document_creator_manual():
    """Manual API endpoint to setup public document creator (for development/troubleshooting)"""
    try:
        return setup_public_document_creator()
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def verify_public_document_creator_manual():
    """Manual API endpoint to verify public document creator setup"""
    try:
        return verify_public_document_creator_setup()
    except Exception as e:
        return {"success": False, "message": str(e)}
