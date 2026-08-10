# Webhook User Setup for Verenigingen App
# Creates and configures a secure webhook user during app installation

import re
import secrets
import string

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


def setup_webhook_user():
    """
    Create and configure a dedicated webhook user with minimal required permissions.

    This function creates a secure webhook user account during app installation to ensure
    production deployments have proper security from day one without manual configuration.

    Returns:
        dict: Status and details of the webhook user setup
    """
    try:
        if frappe.db.get_single_value("Verenigingen Payments Settings", "disable_webhook_user_autosetup"):
            # Escape hatch. Without this there is no supported way to stop the
            # after_migrate hook recreating/re-enabling the account: clearing
            # webhook_user does not help, because generate_webhook_user_email falls
            # through to the canonical address and the setting is rewritten.
            frappe.logger().info("Webhook user auto-setup disabled in Verenigingen Payments Settings")
            return {"success": True, "skipped": True, "message": "Auto-setup disabled in settings"}

        print("🔐 Setting up secure webhook user...")

        webhook_user_email = generate_webhook_user_email()

        # Only mint a password when we are actually going to set one. This used to be
        # generated unconditionally and PRINTED on every successful run -- including
        # runs where the user already existed and the password was never applied, so
        # migrate logs filled with secret-shaped strings that did not open the account.
        webhook_password = None
        if not frappe.db.exists("User", webhook_user_email):
            webhook_password = generate_secure_password()

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

        print("✅ Webhook user setup completed successfully")
        print(f"   📧 User: {webhook_user_email}")
        print("   🛡️ Role: Verenigingen Webhook User")
        print("   ⚙️ Configured in Verenigingen Payments Settings")
        if webhook_password:
            # The password is deliberately NOT printed. This runs on every migrate,
            # so it would land in migrate/CI/supervisor logs -- CodeQL flags it as
            # py/clear-text-logging-sensitive-data, correctly. Nothing needs it to
            # operate: the gateways assume this identity via frappe.set_user, never
            # by logging in. Retrieve it deliberately if a human ever needs it.
            print("   🔐 Password set; retrieve via get_webhook_credentials_manual()")

        result = {
            "success": True,
            "webhook_user_email": webhook_user_email,
            "message": "Webhook user created and configured successfully",
        }
        # Absent, not None, when no password was set -- callers (including the
        # whitelisted setup_webhook_user_manual) must not present a fiction as
        # the account's credential.
        if webhook_password:
            result["webhook_password"] = webhook_password
        return result

    except Exception as e:
        error_msg = f"Failed to setup webhook user: {str(e)}"
        frappe.logger().error(error_msg)
        print(f"❌ {error_msg}")
        return {"success": False, "message": error_msg}


def generate_webhook_user_email():
    """Resolve the webhook user's email. DETERMINISTIC -- the same site always
    resolves to the same address.

    This used to walk a counter *while the user existed*, so it deliberately
    returned an address that did NOT exist yet. The existence check in
    create_webhook_user_account could therefore never fire, and every run minted a
    fresh user (webhook-user-1@, webhook-user-2@, ...). That made setup_webhook_user
    non-idempotent, which is why it could only ever be wired into after_install and
    why sites that missed that one-shot could never converge.

    Resolution order:
      1. Whatever is already configured in Verenigingen Payments Settings, so an
         existing deployment keeps its identity (and a deleted user is recreated at
         the SAME address rather than beside it).
      2. The canonical webhook-user@<site>.
    """
    canonical = _canonical_webhook_email()

    try:
        configured = frappe.db.get_single_value("Verenigingen Payments Settings", "webhook_user")
        if configured:
            # One-time normalisation: `webhook-user-<n>@<this site>` is the fingerprint
            # of the old counter bug. Keeping it would canonicalise that artefact
            # forever and make every future reader re-diagnose it. Only rewrite when
            # the suffixed user does NOT exist -- if it is a live account, moving off
            # it would orphan the identity that documents are attributed to.
            if re.fullmatch(r"webhook-user-\d+@" + re.escape(canonical.split("@", 1)[1]), configured):
                if not frappe.db.exists("User", configured):
                    return canonical
            return configured
    except Exception:
        pass

    return canonical


def _canonical_webhook_email():
    """webhook-user@<site>, with the site name made valid as an email domain."""
    try:
        site_name = frappe.conf.site_name or frappe.local.site
        # Clean the site name for use as an email domain. Dots MUST be preserved
        # (a dot-less domain like "veg11-veganisme-org" fails Frappe's email
        # validation); only underscores (invalid in domains) are replaced, and a
        # ".local" suffix is appended when the site name has no dot at all.
        clean_site = site_name.replace("_", "-")
        if "." not in clean_site:
            clean_site = f"{clean_site}.local"
        return f"webhook-user@{clean_site}"

    except Exception:
        return "webhook-user@verenigingen-app.local"


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
            # Converge rather than no-op: get_service_user() treats a DISABLED user
            # exactly like an unset one and silently falls back to Administrator, so
            # leaving it disabled would leave the whole scoped-service-user model off.
            if not frappe.db.get_value("User", webhook_email, "enabled"):
                # Save the doc rather than db_set: db_set bypasses User.on_update, so
                # the role cache is never cleared and no Version row records the
                # change -- an account re-enabled behind an operator's back with no
                # audit trail. Someone may have disabled it deliberately, so this is
                # also logged, and the whole hook can be switched off via
                # Verenigingen Payments Settings.disable_webhook_user_autosetup.
                existing = frappe.get_doc("User", webhook_email)
                existing.enabled = 1
                existing.save(ignore_permissions=True)
                frappe.db.commit()
                frappe.log_error(
                    title="Webhook User Re-enabled by Setup",
                    message=(
                        f"{webhook_email} was disabled and has been re-enabled by "
                        f"setup_webhook_user (runs on every migrate). If this was "
                        f"disabled deliberately, set "
                        f"Verenigingen Payments Settings.disable_webhook_user_autosetup."
                    ),
                )
                print(f"   ✅ Re-enabled existing webhook user: {webhook_email}")
                return {"success": True, "message": f"Webhook user {webhook_email} re-enabled"}

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

        # Set the role profile. Frappe v16 moved role profiles to the
        # `role_profiles` child table; setting the deprecated scalar
        # `role_profile_name` directly is nulled out on save when the child
        # table is empty (User.move_role_profile_name_to_role_profiles). We must
        # append to `role_profiles` instead — User.sync_role_profile_name then
        # repopulates role_profile_name from it for display/verification.
        has_role_profile = any(
            rp.role_profile == "Verenigingen Webhook User" for rp in user_doc.role_profiles
        )
        if not has_role_profile:
            user_doc.append("role_profiles", {"role_profile": "Verenigingen Webhook User"})

        # Ensure the Module Profile exists before linking it. In production the
        # v2_1 sync_module_profiles patch creates it during migrate, but on a fresh
        # site (or a test DB where this setup runs before that patch) the record is
        # absent and assigning a non-existent Module Profile fails User validation.
        # Create it idempotently, mirroring the patch's in_install flag handling
        # (its Module Profile on_update queues a locked background job otherwise).
        if not frappe.db.exists("Module Profile", "Verenigingen Webhook User"):
            from verenigingen.patches.v2_1.sync_module_profiles_safely import sync_module_profiles

            original_in_install = frappe.flags.in_install
            frappe.flags.in_install = True
            try:
                sync_module_profiles()
            finally:
                frappe.flags.in_install = original_in_install
        needs_module_profile = user_doc.module_profile != "Verenigingen Webhook User"
        if needs_module_profile:
            user_doc.module_profile = "Verenigingen Webhook User"

        # Save ONLY when something actually changed. This runs on every migrate now,
        # and an unconditional save bumps `modified` and re-fires the whole User
        # on_update chain (role-cache invalidation, field sync, desk settings,
        # chapter permission cleanup) plus Frappe's own share/role work, every time.
        if not (has_webhook_role and has_role_profile) or needs_module_profile:
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
        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

        # Get or create the payments settings
        if not DocumentExistenceValidator.validate_document_exists(
            "Verenigingen Payments Settings", "Verenigingen Payments Settings", throw_on_error=False
        ):
            settings_doc = frappe.get_doc({"doctype": "Verenigingen Payments Settings"})
            settings_doc.insert(ignore_permissions=True)
        else:
            settings_doc = frappe.get_doc("Verenigingen Payments Settings", "Verenigingen Payments Settings")

        # Only save when it actually changes -- this runs on every migrate, and an
        # unconditional save bumps `modified` on the Single and re-runs its validate()
        # each time.
        if settings_doc.webhook_user != webhook_email:
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
@high_security_api(operation_type=OperationType.ADMIN)
def setup_webhook_user_manual():
    """Manual API endpoint to setup webhook user (for development/troubleshooting)"""
    try:
        result = setup_webhook_user()
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
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

        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

        if not DocumentExistenceValidator.validate_document_exists(
            "User", webhook_user, throw_on_error=False
        ):
            return {"success": False, "message": "Configured webhook user does not exist"}

        return {
            "success": True,
            "webhook_user_email": webhook_user,
            "message": "Webhook user is configured and active",
        }

    except Exception as e:
        return {"success": False, "message": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_webhook_credentials_manual():
    """Manual API endpoint to get webhook credentials for display"""
    try:
        result = get_webhook_credentials_for_display()
        return result
    except Exception as e:
        return {"success": False, "message": str(e)}
