# Public Document Creator User Setup for Verenigingen App
# Creates and configures a secure system user for public-facing document creation
# (donations, member applications, etc.)

import re

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.utils.user_role_grant import ensure_role_survives_profile_resync

# Role name constant.
#
# SECURITY (#1670): the Custom DocPerm rows this role carries (read/write/create on Donor,
# Donation, Member, Address, Contact, no if_owner) are only as safe as the account is
# unreachable. Measured on a test site: as this user, get_list returns EVERY Contact (and may
# write it) and every Donation row; Donor/Member/Address are refused by the app's
# has_permission hooks and list queries, which also refuse it CREATE on those four doctypes.
# So the account is never logged in as: the public flows only impersonate it in-process
# (secure_user_context -> frappe.set_user). It therefore holds NO password or API key, and
# refuse_public_creator_authentication() refuses it on every login and every request.
PUBLIC_CREATOR_ROLE = "Verenigingen Public Document Creator"

# The address generate_public_creator_email() mints: public-creator@<domain> or public-creator-N@<domain>.
_CREATOR_ADDRESS = re.compile(r"^public-creator(-\d+)?@", re.IGNORECASE)


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

        # Reuse an existing creator rather than minting public-creator-N on every run
        # (setup is run by every fresh install and by the manual endpoint).
        user_email = find_existing_public_creator()
        if not user_email:
            user_email = generate_public_creator_email()
            user_result = create_public_creator_account(user_email)
            if not user_result["success"]:
                return user_result

        # Assign roles
        role_result = assign_public_creator_roles(user_email)
        if not role_result["success"]:
            return role_result

        # An account reused from before #1670 still carries its password / API key / sessions.
        lock_public_creator_credentials(user_email)

        # Configure in Verenigingen Settings as creation_user
        config_result = configure_creation_user_in_settings(user_email)
        if not config_result["success"]:
            return config_result

        print("✅ Public document creator setup completed successfully")
        print(f"   📧 User: {user_email}")
        print(f"   🛡️ Role: {PUBLIC_CREATOR_ROLE}")
        print("   ⚙️ Configured as creation_user in Verenigingen Settings")

        return {
            "success": True,
            "user_email": user_email,
            "message": "Public document creator setup completed successfully",
        }

    except Exception as e:
        error_msg = f"Failed to setup public document creator: {str(e)}"
        frappe.logger().error(error_msg)
        print(f"❌ {error_msg}")
        return {"success": False, "message": error_msg}


def find_existing_public_creator():
    """Email of an existing enabled public-creator user that may be reused, else None.

    The `public-creator` name prefix is the only identifier, so it is not trusted alone: the
    user must hold the creator role and NO other role (a user that also holds e.g. System
    Manager is never silently adopted as the least-privilege creation user).
    """
    rows = frappe.get_all(
        "User",
        filters={"name": ["like", "public-creator%"], "enabled": 1},
        pluck="name",
        order_by="name asc",
    )
    for email in rows:
        roles = set(frappe.get_all("Has Role", filters={"parent": email}, pluck="role"))
        if roles == {PUBLIC_CREATOR_ROLE}:
            return email
    return None


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

        # Grant minimal permissions to the role via the framework API.
        #
        # IMPORTANT: use frappe.permissions.add_permission, NOT a raw Custom DocPerm
        # insert. add_permission() first runs setup_custom_perms() -> copy_perms(),
        # which clones every existing standard DocPerm into Custom DocPerm BEFORE
        # adding this role — preserving all other roles' permissions. Frappe treats a
        # doctype's Custom DocPerm set as authoritative once ANY Custom DocPerm row
        # exists, so inserting a lone raw row (without copy_perms first) would
        # silently drop every standard permission on core doctypes like
        # Member/Donor/Donation.
        from frappe.permissions import add_permission, update_permission_property

        managed_doctypes = ["Donor", "Donation", "Member", "Address", "Contact"]
        for doctype in managed_doctypes:
            if frappe.db.exists(
                "Custom DocPerm",
                {"parent": doctype, "role": PUBLIC_CREATOR_ROLE, "permlevel": 0},
            ):
                continue
            add_permission(doctype, PUBLIC_CREATOR_ROLE, 0)  # creates the row with read=1 (+ copy_perms)
            update_permission_property(doctype, PUBLIC_CREATOR_ROLE, 0, "write", 1, validate=False)
            update_permission_property(doctype, PUBLIC_CREATOR_ROLE, 0, "create", 1, validate=False)

        frappe.db.commit()
        print(f"   ✅ Created role {PUBLIC_CREATOR_ROLE} with minimal permissions")
        return {"success": True, "message": f"Role {PUBLIC_CREATOR_ROLE} created"}

    except Exception as e:
        error_msg = f"Failed to create role: {str(e)}"
        print(f"   ❌ {error_msg}")
        return {"success": False, "message": error_msg}


def lock_public_creator_credentials(user_email):
    """Strip every credential the creator account could be authenticated with (#1670).

    Idempotent. Removes the stored password and API secret, the API key, a pending password
    reset key and every live session. Leaves the account enabled and holding its role: the
    public flows still `frappe.set_user()` it in-process, which needs none of these.
    No commit here: both callers (setup, after_migrate) commit themselves.
    """
    from frappe.sessions import clear_sessions
    from frappe.utils.password import delete_all_passwords_for

    delete_all_passwords_for("User", user_email)
    frappe.db.set_value(
        "User",
        user_email,
        {"api_key": None, "reset_password_key": None, "last_reset_password_key_generated_on": None},
        update_modified=False,
    )
    clear_sessions(user_email, force=True)


def harden_public_document_creator():
    """after_migrate: lock the credentials of a creator that predates #1670.

    Sites set up before then hold an account with a password, and install + migrate keep
    the account. Every account `is_public_creator()` recognises is locked, whatever other
    roles it has since been given (role-profile sync can add some).
    """
    holders = frappe.get_all(
        "Has Role", filters={"role": PUBLIC_CREATOR_ROLE, "parenttype": "User"}, pluck="parent"
    )
    for user in sorted(set(holders)):
        if is_public_creator(user):
            lock_public_creator_credentials(user)


def is_public_creator(user):
    """True for the account setup creates: it holds the creator role AND has the address
    `generate_public_creator_email()` mints (`public-creator[-N]@<domain>`).

    Both are required. The role alone would lock out a staff user who was granted it; the
    address alone would catch a staff user who merely has a similar name. Other roles are
    irrelevant on purpose: a creator that gained a role must still never log in. (Not keyed on
    `Verenigingen Settings.creation_user`: that can be any real account, e.g. veg11's.)
    """
    if not user or not _CREATOR_ADDRESS.match(user):
        return False
    return PUBLIC_CREATOR_ROLE in frappe.get_roles(user)


def refuse_public_creator_authentication(login_manager=None):
    """auth_hooks / on_login hook: the creator account can never hold a session (#1670).

    `auth_hooks` runs on every request after the session, an API key or a bearer token has set
    the user, `on_login` after a password (or social/OTP) login succeeded. Both refuse exactly
    as Frappe refuses a wrong password, so a refusal is not distinguishable from one.
    The public flows are unaffected: they switch user in-process and never come through here.
    """
    if login_manager is not None:
        if is_public_creator(login_manager.user):
            # A password set later (reset, admin) must not linger: fail() commits this too.
            lock_public_creator_credentials(login_manager.user)
            login_manager.fail("Invalid login credentials", user=login_manager.user)
    elif is_public_creator(frappe.session.user):
        raise frappe.AuthenticationError


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
        # A dotless domain is not a valid email address. Production site names are
        # FQDNs (they have a dot), but a bare site name such as the CI "test_site"
        # sanitises to "test-site" with no TLD and would fail User email validation
        # — and thus the whole setup. Fall back to a .local TLD in that case.
        if "." not in clean_site:
            clean_site = f"{clean_site}.local"
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


def create_public_creator_account(user_email):
    """Create the public document creator user account.

    Deliberately WITHOUT a password (#1670): nothing logs in as this user, so a stored
    credential could only ever be used against us.
    """
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
            # #1195: the append above is silently defeated by User.validate()'s
            # role-profile re-derivation if this (existing) user carries a Role
            # Profile that doesn't include PUBLIC_CREATOR_ROLE -- verify and
            # fall back to a direct Has Role insert.
            ensure_role_survives_profile_resync(user_email, PUBLIC_CREATOR_ROLE)
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
        # frappe.db.exists(dt, dt) is unconditionally truthy for a Single (#889), so this skip
        # never fired on a site whose Settings were not saved yet and the get_doc/save below
        # then failed on the mandatory `company` (#1647).
        if not frappe.db.get_singles_dict("Verenigingen Settings"):
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

        # Check settings. frappe.db.exists(dt, dt) is unconditionally truthy
        # for a Single (#889); check whether it has actually been saved
        # instead, so this diagnostic reflects real configuration state.
        if frappe.db.get_singles_dict("Verenigingen Settings"):
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
