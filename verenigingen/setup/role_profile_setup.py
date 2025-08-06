"""
Role Profile Setup Script for Verenigingen

This script helps set up and assign role profiles to users based on their function.
"""

import frappe
from frappe import _


def setup_role_profiles():
    """
    Setup role profiles and module profiles for the Verenigingen app.
    This function should be called after installing the fixtures.
    """

    # Map role profiles to module profiles
    role_module_mapping = {
        "Verenigingen Member": "Verenigingen Basic Access",
        "Verenigingen Volunteer": "Verenigingen Volunteer Access",
        "Verenigingen Team Leader": "Verenigingen Volunteer Access",
        "Verenigingen Chapter Board": "Verenigingen Volunteer Access",
        "Verenigingen Treasurer": "Verenigingen Financial Access",
        "Verenigingen Chapter Administrator": "Verenigingen Management Access",
        "Verenigingen Manager": "Verenigingen Management Access",
        "Verenigingen Financial Manager": "Verenigingen Financial Access",  # Consolidates Bank Reconciliation User
        "Verenigingen System Administrator": None,  # Full access
        "Verenigingen Auditor": "Verenigingen Audit Access",  # Uses ERPNext Auditor role
    }

    # Assign module profiles to role profiles
    for role_profile_name, module_profile_name in role_module_mapping.items():
        try:
            if frappe.db.exists("Role Profile", role_profile_name):
                role_profile = frappe.get_doc("Role Profile", role_profile_name)

                if module_profile_name and frappe.db.exists("Module Profile", module_profile_name):
                    # Clear existing module profile links
                    role_profile.module_profile = module_profile_name
                    role_profile.save(ignore_permissions=True)
                    frappe.db.commit()
                    print(
                        f"✓ Assigned module profile '{module_profile_name}' to role profile '{role_profile_name}'"
                    )

        except Exception as e:
            print(f"✗ Error setting up {role_profile_name}: {str(e)}")
            frappe.log_error(f"Role Profile Setup Error: {str(e)}", "Role Profile Setup")


@frappe.whitelist()
def assign_role_profile_to_user(user: str, role_profile: str) -> None:
    """
    Assign a role profile to a user.

    Args:
        user: User email/name
        role_profile: Name of the role profile
    """
    if not frappe.db.exists("User", user):
        frappe.throw(_("User {0} does not exist").format(user))

    if not frappe.db.exists("Role Profile", role_profile):
        frappe.throw(_("Role Profile {0} does not exist").format(role_profile))

    user_doc = frappe.get_doc("User", user)

    # Check if role profile is already assigned (Frappe v15 uses single field)
    existing_role_profile = user_doc.get("role_profile_name")
    if existing_role_profile != role_profile:
        user_doc.role_profile_name = role_profile
        user_doc.save(ignore_permissions=True)
        frappe.msgprint(_("Role Profile {0} assigned to user {1}").format(role_profile, user))
    else:
        frappe.msgprint(_("User {0} already has role profile {1}").format(user, role_profile))


def get_recommended_role_profile(user: str) -> str | None:
    """
    Recommend a role profile based on user's existing roles and associations.

    Args:
        user: User email/name

    Returns:
        Recommended role profile name or None
    """
    # Check if user is linked to a member
    member = frappe.db.get_value("Member", {"user": user}, "name")
    if not member:
        return None

    # Check various associations in order of precedence

    # 1. System Administrator
    user_roles = frappe.get_roles(user)
    if "System Manager" in user_roles or "Administrator" in user_roles:
        return "Verenigingen System Administrator"

    # 2. Manager roles
    if "Verenigingen Manager" in user_roles:
        return "Verenigingen Manager"

    # 3. Staff roles
    if "Verenigingen Staff" in user_roles:
        # Further check for specific staff roles
        if "Accounts User" in user_roles:
            return "Verenigingen Treasurer"
        else:
            return "Verenigingen Chapter Administrator"

    # 4. Governance roles
    if "Verenigingen Governance Auditor" in user_roles:
        return "Verenigingen Auditor"

    # 5. Chapter Board roles
    if "Verenigingen Chapter Board Member" in user_roles:
        return "Verenigingen Chapter Board"

    # 6. Volunteer roles
    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
    if volunteer:
        # Check if team leader
        team_member = frappe.db.get_value(
            "Team Member", {"volunteer": volunteer, "role_type": "Leader"}, "name"
        )
        if team_member:
            return "Verenigingen Team Leader"
        else:
            return "Verenigingen Volunteer"

    # 7. Basic member
    if "Verenigingen Member" in user_roles:
        return "Verenigingen Member"

    return None


@frappe.whitelist()
def auto_assign_role_profiles():
    """
    Automatically assign role profiles to existing users based on their current roles.
    This is useful for initial setup after installing the role profiles.
    """
    users_updated = 0
    errors = []

    # Get all active users who are members
    members_with_users = frappe.get_all(
        "Member", filters={"user": ["!=", ""]}, fields=["name", "user", "full_name"]
    )

    for member in members_with_users:
        try:
            user = member.user
            recommended_profile = get_recommended_role_profile(user)

            if recommended_profile:
                # Check if user already has any verenigingen role profile
                user_doc = frappe.get_doc("User", user)
                existing_profiles = [rp.role_profile for rp in user_doc.role_profiles]

                verenigingen_profiles = [p for p in existing_profiles if p.startswith("Verenigingen")]

                if not verenigingen_profiles:
                    # Assign the recommended profile
                    assign_role_profile_to_user(user, recommended_profile)
                    users_updated += 1
                    print(f"✓ Assigned {recommended_profile} to {user} ({member.member_name})")

        except Exception as e:
            error_msg = f"Error processing user {member.user}: {str(e)}"
            errors.append(error_msg)
            print(f"✗ {error_msg}")

    print(f"\nSummary: Updated {users_updated} users")
    if errors:
        print(f"Errors: {len(errors)}")
        for error in errors[:5]:  # Show first 5 errors
            print(f"  - {error}")

    return {"users_updated": users_updated, "errors": errors}


def install_fixtures():
    """
    Install the role profile fixtures.
    This should be called during app installation or update.
    """
    from frappe.desk.page.setup_wizard.install_fixtures import install_fixtures as install_fixtures_frappe

    # Install role profiles
    install_fixtures_frappe("verenigingen")

    # Setup module profile assignments
    setup_role_profiles()

    print("Role profiles and module profiles have been installed successfully.")


def setup_role_profiles_cli():
    """
    CLI-friendly version of role profile setup that provides detailed console output.
    This function is specifically designed for command-line execution via bench execute.
    It bypasses all security decorators and directly performs the setup.

    Returns:
        dict: Setup results with CLI-friendly output
    """
    try:
        print("🚀 Starting role profile setup...")

        # Setup role profiles directly
        # Map role profiles to module profiles
        role_module_mapping = {
            "Verenigingen Member": "Verenigingen Basic Access",
            "Verenigingen Volunteer": "Verenigingen Volunteer Access",
            "Verenigingen Team Leader": "Verenigingen Volunteer Access",
            "Verenigingen Chapter Board": "Verenigingen Volunteer Access",
            "Verenigingen Treasurer": "Verenigingen Financial Access",
            "Verenigingen Chapter Administrator": "Verenigingen Management Access",
            "Verenigingen Manager": "Verenigingen Management Access",
            "Verenigingen System Administrator": None,  # Full access
            "Verenigingen Auditor": "Verenigingen Audit Access",
        }

        # Assign module profiles to role profiles
        for role_profile_name, module_profile_name in role_module_mapping.items():
            try:
                if frappe.db.exists("Role Profile", role_profile_name):
                    role_profile = frappe.get_doc("Role Profile", role_profile_name)

                    if module_profile_name and frappe.db.exists("Module Profile", module_profile_name):
                        # Clear existing module profile links
                        role_profile.module_profile = module_profile_name
                        role_profile.save(ignore_permissions=True)
                        frappe.db.commit()
                        print(
                            f"✅ Assigned module profile '{module_profile_name}' to role profile '{role_profile_name}'"
                        )
                    else:
                        print(
                            f"ℹ️  Skipping '{role_profile_name}' - module profile not found or not required"
                        )

            except Exception as e:
                print(f"❌ Error setting up {role_profile_name}: {str(e)}")
                frappe.log_error(f"Role Profile Setup Error: {str(e)}", "Role Profile Setup")

        print("✅ Role profiles configured successfully")

        # Auto-assign to users
        print("\n👥 Auto-assigning role profiles to users...")

        users_updated = 0
        errors = []

        # Get all active users who are members
        members_with_users = frappe.get_all(
            "Member", filters={"user": ["!=", ""]}, fields=["name", "user", "full_name"]
        )

        for member in members_with_users:
            try:
                user = member.user

                # Check if user is linked to a member
                if not frappe.db.exists("Member", {"user": user}):
                    continue

                # Get user roles for recommendation logic
                user_roles = frappe.get_roles(user)
                recommended_profile = None

                # System Administrator
                if "System Manager" in user_roles or "Administrator" in user_roles:
                    recommended_profile = "Verenigingen System Administrator"
                # Manager roles
                elif "Verenigingen Manager" in user_roles:
                    recommended_profile = "Verenigingen Manager"
                # Staff roles
                elif "Verenigingen Staff" in user_roles:
                    if "Accounts User" in user_roles:
                        recommended_profile = "Verenigingen Treasurer"
                    else:
                        recommended_profile = "Verenigingen Chapter Administrator"
                # Governance roles
                elif "Verenigingen Governance Auditor" in user_roles:
                    recommended_profile = "Verenigingen Auditor"
                # Chapter Board roles
                elif "Verenigingen Chapter Board Member" in user_roles:
                    recommended_profile = "Verenigingen Chapter Board"
                # Volunteer roles
                elif frappe.db.get_value("Volunteer", {"member": member.name}, "name"):
                    # Check if team leader
                    volunteer = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
                    team_member = frappe.db.get_value(
                        "Team Member", {"volunteer": volunteer, "role_type": "Leader"}, "name"
                    )
                    if team_member:
                        recommended_profile = "Verenigingen Team Leader"
                    else:
                        recommended_profile = "Verenigingen Volunteer"
                # Basic member
                elif "Verenigingen Member" in user_roles:
                    recommended_profile = "Verenigingen Member"

                if recommended_profile:
                    # Check if user already has any verenigingen role profile (Frappe v15 single field)
                    user_doc = frappe.get_doc("User", user)
                    existing_profile = user_doc.get("role_profile_name") or ""

                    if not existing_profile.startswith("Verenigingen"):
                        # Assign the recommended profile
                        user_doc.role_profile_name = recommended_profile
                        user_doc.save(ignore_permissions=True)
                        users_updated += 1
                        print(f"✅ Assigned {recommended_profile} to {user} ({member.full_name})")
                    else:
                        print(f"ℹ️  {user} already has role profile: {existing_profile}")

            except Exception as e:
                error_msg = f"Error processing user {member.user}: {str(e)}"
                errors.append(error_msg)
                print(f"❌ {error_msg}")

        print("\n📊 Setup completed successfully!")
        print(f"   Users updated: {users_updated}")
        print(f"   Errors: {len(errors)}")

        if errors:
            print("\n⚠️ Errors encountered:")
            for error in errors[:3]:  # Show first 3 errors
                print(f"   - {error}")

        return {
            "success": True,
            "message": "Role profiles setup completed successfully",
            "users_updated": users_updated,
            "errors": errors,
        }

    except Exception as e:
        error_msg = f"CLI role profile setup failed: {str(e)}"
        print(f"❌ {error_msg}")
        frappe.log_error(error_msg, "CLI Role Profile Setup")
        return {"success": False, "error": str(e), "message": error_msg}


@frappe.whitelist()
def deploy_role_profiles():
    """
    Deploy and setup role profiles for the Verenigingen app.
    This is a wrapper function that calls the enhanced deployment script
    and provides compatibility with documentation references.

    Returns:
        dict: Deployment results with status information
    """
    try:
        # First setup basic role profiles
        setup_role_profiles()

        # Then auto-assign to existing users
        assign_result = auto_assign_role_profiles()

        return {
            "success": True,
            "message": "Role profiles deployed successfully",
            "setup_completed": True,
            "users_updated": assign_result.get("users_updated", 0),
            "errors": assign_result.get("errors", []),
            "recommendation": "For enhanced profiles, run: python scripts/setup/deploy_role_profiles.py",
        }

    except Exception as e:
        frappe.log_error(f"Deploy role profiles error: {str(e)}", "Role Profile Deployment")
        return {
            "success": False,
            "message": f"Deployment failed: {str(e)}",
            "recommendation": "Check error logs and try manual setup_role_profiles() function",
        }


if __name__ == "__main__":
    # If run directly, perform auto-assignment
    auto_assign_role_profiles()
