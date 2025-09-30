#!/usr/bin/env python3

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
"""
Deploy Enhanced Role Profiles for Verenigingen

This script helps deploy the enhanced role profiles and module profiles,
replacing or updating the existing ones.
"""

import json
import os

import frappe


def deploy_enhanced_profiles():
    """Deploy the enhanced role and module profiles"""

    print("=== Deploying Enhanced Role Profiles ===\n")

    # Get the fixtures directory
    app_path = frappe.get_app_path("verenigingen")
    fixtures_path = os.path.join(app_path, "fixtures")

    # Check if enhanced files exist
    enhanced_role_profile_path = os.path.join(fixtures_path, "role_profile_enhanced.json")
    enhanced_module_profile_path = os.path.join(fixtures_path, "module_profile_enhanced.json")

    if not os.path.exists(enhanced_role_profile_path):
        print(
            "❌ Enhanced role profile file not found. Please ensure role_profile_enhanced.json exists in fixtures/"
        )
        return

    if not os.path.exists(enhanced_module_profile_path):
        print(
            "❌ Enhanced module profile file not found. Please ensure module_profile_enhanced.json exists in fixtures/"
        )
        return

    # Backup existing profiles
    backup_existing_profiles()

    # Deploy module profiles first
    print("\n📦 Deploying Module Profiles...")
    deploy_module_profiles(enhanced_module_profile_path)

    # Deploy role profiles
    print("\n👥 Deploying Role Profiles...")
    deploy_role_profiles_from_file(enhanced_role_profile_path)

    # Link module profiles to role profiles
    print("\n🔗 Linking Module Profiles to Role Profiles...")
    link_module_profiles()

    print("\n✅ Deployment complete!")
    print("\nNext steps:")
    print("1. Run: bench --site [sitename] clear-cache")
    print("2. Test with a sample user")
    print("3. Run auto-assignment if needed: python scripts/setup/auto_assign_profiles.py")


def backup_existing_profiles():
    """Backup existing role and module profiles"""
    print("\n💾 Backing up existing profiles...")

    # Backup role profiles
    role_profiles = frappe.get_all("Role Profile", filters={"name": ["like", "Verenigingen%"]}, fields=["*"])

    if role_profiles:
        backup_data = []
        for rp in role_profiles:
            doc = frappe.get_doc("Role Profile", rp.name)
            backup_data.append(doc.as_dict())

        backup_path = os.path.join(
            frappe.get_app_path("verenigingen"), "fixtures", "role_profile_backup.json"
        )
        with open(backup_path, "w") as f:
            json.dump(backup_data, f, indent=2, default=str)
        print(f"  ✓ Backed up {len(backup_data)} role profiles to role_profile_backup.json")

    # Backup module profiles
    module_profiles = frappe.get_all(
        "Module Profile", filters={"name": ["like", "Verenigingen%"]}, fields=["*"]
    )

    if module_profiles:
        backup_data = []
        for mp in module_profiles:
            doc = frappe.get_doc("Module Profile", mp.name)
            backup_data.append(doc.as_dict())

        backup_path = os.path.join(
            frappe.get_app_path("verenigingen"), "fixtures", "module_profile_backup.json"
        )
        with open(backup_path, "w") as f:
            json.dump(backup_data, f, indent=2, default=str)
        print(f"  ✓ Backed up {len(backup_data)} module profiles to module_profile_backup.json")


def deploy_module_profiles(file_path):
    """Deploy module profiles from file"""
    with open(file_path, "r") as f:
        module_profiles = json.load(f)

    for mp_data in module_profiles:
        try:
            # Check if exists
            if DocumentExistenceValidator.check_document_exists("Module Profile", mp_data["name"]):
                # Update existing
                doc = frappe.get_doc("Module Profile", mp_data["name"])
                doc.modules = []  # Clear existing modules

                for module in mp_data.get("modules", []):
                    doc.append("modules", module)

                doc.save(ignore_permissions=True)
                print(f"  ✓ Updated module profile: {mp_data['name']}")
            else:
                # Create new
                doc = frappe.get_doc(mp_data)
                doc.insert(ignore_permissions=True)
                print(f"  ✓ Created module profile: {mp_data['name']}")

        except Exception as e:
            print(f"  ❌ Error with module profile {mp_data['name']}: {str(e)}")

    frappe.db.commit()


def deploy_role_profiles_from_file(file_path):
    """Deploy role profiles from file"""
    with open(file_path, "r") as f:
        role_profiles = json.load(f)

    for rp_data in role_profiles:
        try:
            # Check if exists
            if DocumentExistenceValidator.check_document_exists("Role Profile", rp_data["name"]):
                # Update existing
                doc = frappe.get_doc("Role Profile", rp_data["name"])
                doc.roles = []  # Clear existing roles

                for role in rp_data.get("roles", []):
                    doc.append("roles", role)

                doc.save(ignore_permissions=True)
                print(f"  ✓ Updated role profile: {rp_data['name']}")
            else:
                # Create new
                doc = frappe.get_doc(rp_data)
                doc.insert(ignore_permissions=True)
                print(f"  ✓ Created role profile: {rp_data['name']}")

        except Exception as e:
            print(f"  ❌ Error with role profile {rp_data['name']}: {str(e)}")

    frappe.db.commit()


def link_module_profiles():
    """Link module profiles to role profiles"""

    # Enhanced mapping with new profiles
    role_module_mapping = {
        "Verenigingen Member": "Verenigingen Basic Access",
        "Verenigingen Volunteer": "Verenigingen Volunteer Access",
        "Verenigingen Team Leader": "Verenigingen Team Management Access",
        "Verenigingen Chapter Board Member": "Verenigingen Volunteer Access",
        "Verenigingen Treasurer": "Verenigingen Financial Access",
        "Verenigingen Chapter Administrator": "Verenigingen Management Access",
        "Verenigingen Communications Officer": "Verenigingen Communications Access",
        "Verenigingen Event Coordinator": "Verenigingen Volunteer Access",
        "Verenigingen Staff": "Verenigingen Management Access",
        "Verenigingen Finance Manager": "Verenigingen Finance Management Access",
        "Verenigingen System Administrator": None,  # Full access
        "Verenigingen Auditor": "Verenigingen Audit Access",
        "Verenigingen Guest": "Verenigingen Guest Access",
    }

    for role_profile_name, module_profile_name in role_module_mapping.items():
        try:
            if DocumentExistenceValidator.check_document_exists("Role Profile", role_profile_name):
                role_profile = frappe.get_doc("Role Profile", role_profile_name)

                if module_profile_name and DocumentExistenceValidator.check_document_exists("Module Profile", module_profile_name):
                    role_profile.module_profile = module_profile_name
                    role_profile.save(ignore_permissions=True)
                    print(f"  ✓ Linked '{module_profile_name}' to '{role_profile_name}'")
                elif not module_profile_name:
                    print(f"  ℹ️  No module profile for '{role_profile_name}' (full access)")
                else:
                    print(f"  ⚠️  Module profile '{module_profile_name}' not found")

        except Exception as e:
            print(f"  ❌ Error linking {role_profile_name}: {str(e)}")

    frappe.db.commit()


def show_profile_summary():
    """Show summary of deployed profiles"""
    print("\n📊 Deployment Summary:")

    # Count role profiles
    role_profiles = frappe.get_all("Role Profile", filters={"name": ["like", "Verenigingen%"]})
    print(f"\n  Role Profiles: {len(role_profiles)}")
    for rp in role_profiles:
        doc = frappe.get_doc("Role Profile", rp.name)
        print(f"    - {rp.name} ({len(doc.roles)} roles)")

    # Count module profiles
    module_profiles = frappe.get_all("Module Profile", filters={"name": ["like", "Verenigingen%"]})
    print(f"\n  Module Profiles: {len(module_profiles)}")
    for mp in module_profiles:
        doc = frappe.get_doc("Module Profile", mp.name)
        print(f"    - {mp.name} ({len(doc.modules)} modules)")


if __name__ == "__main__":
    frappe.connect(site=frappe.get_site())

    try:
        deploy_enhanced_profiles()
        show_profile_summary()
    except Exception as e:
        print(f"\n❌ Deployment failed: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.db.commit()
        frappe.destroy()
