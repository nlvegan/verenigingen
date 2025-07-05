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
                        f"✓ Assigned module profile '{module_profile_name}' to role profile '{role_profile_name}'"
                    )

        except Exception as e:
            print(f"✗ Error setting up {role_profile_name}: {str(e)}")
            frappe.log_error(f"Role Profile Setup Error: {str(e)}", "Role Profile Setup")


@frappe.whitelist()
def assign_role_profile_to_user(user, role_profile):
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

    # Check if role profile is already assigned
    existing = [rp.role_profile for rp in user_doc.role_profiles]
    if role_profile not in existing:
        user_doc.append("role_profiles", {"role_profile": role_profile})
        user_doc.save(ignore_permissions=True)
        frappe.msgprint(_("Role Profile {0} assigned to user {1}").format(role_profile, user))
    else:
        frappe.msgprint(_("User {0} already has role profile {1}").format(user, role_profile))


def get_recommended_role_profile(user):
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
    if "Governance Auditor" in user_roles:
        return "Verenigingen Auditor"

    # 5. Chapter Board roles
    if "Chapter Board Member" in user_roles:
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
        "Member", filters={"user": ["!=", ""]}, fields=["name", "user", "member_name"]
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


if __name__ == "__main__":
    # If run directly, perform auto-assignment
    auto_assign_role_profiles()
