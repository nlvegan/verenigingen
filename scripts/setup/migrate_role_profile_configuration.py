#!/usr/bin/env python3
"""
Migration and Testing Script for Enhanced Role Profile Assignment System

This script helps migrate from the old hardcoded role profile system to the new
configurable system, and provides testing utilities.

Usage:
    python scripts/setup/migrate_role_profile_configuration.py

Author: Verenigingen Development Team
"""

import frappe


def setup_clean_system():
    """Setup the new clean role profile system without hardcoded fallbacks"""
    
    print("=== ENHANCED ROLE PROFILE SYSTEM SETUP ===")
    print("")
    print("The new system requires explicit configuration for each team and chapter.")
    print("No hardcoded fallbacks - everything must be configured through the UI.")
    print("")
    print("Setup Steps:")
    print("1. Configure Team role profiles")
    print("2. Configure Chapter board role profiles")
    print("3. Test configurations")
    print("4. Apply to existing members")
    print("")
    
    # Initialize Frappe
    frappe.init(site=frappe.local.site)
    frappe.connect()
    
    try:
        # 1. Show Team configuration requirements
        migrate_team_configurations()
        
        # 2. Show Chapter configuration requirements  
        migrate_chapter_configurations()
        
        # 3. Test the new system
        test_enhanced_system()
        
        frappe.db.commit()
        print("\n✅ SYSTEM VALIDATION COMPLETED!")
        
    except Exception as e:
        frappe.db.rollback()
        print(f"\n❌ SETUP VALIDATION FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        frappe.destroy()


def migrate_team_configurations():
    """Migrate existing team role profile assignments"""
    
    print("\n--- Migrating Team Configurations ---")
    
    # Since hardcoded mappings were removed in the refactoring, 
    # we need to provide a migration mapping here
    LEGACY_TEAM_MAPPINGS = {
        "Kascommissie": "Verenigingen Auditor",
        "Communications Team": "Verenigingen Volunteer",
        # Add other known team mappings here based on historical configuration
    }
    
    migrated_teams = 0
    
    for team_name, role_profile in LEGACY_TEAM_MAPPINGS.items():
        try:
            # Check if team exists
            if not frappe.db.exists("Team", team_name):
                print(f"⚠️  Team '{team_name}' does not exist, skipping")
                continue
            
            team_doc = frappe.get_doc("Team", team_name)
            
            # Only migrate if not already configured
            if not team_doc.default_role_profile:
                team_doc.default_role_profile = role_profile
                team_doc.save()
                migrated_teams += 1
                print(f"✅ Migrated team '{team_name}' → '{role_profile}'")
            else:
                print(f"ℹ️  Team '{team_name}' already configured")
                
        except Exception as e:
            print(f"❌ Error migrating team '{team_name}': {str(e)}")
    
    print(f"Migrated {migrated_teams} team configurations")


def migrate_chapter_configurations():
    """Migrate existing chapter role profile assignments"""
    
    print("\n--- Migrating Chapter Configurations ---")
    
    # Since hardcoded mappings were removed in the refactoring,
    # use a sensible default for chapter board role profiles
    default_profile = "Verenigingen Chapter Board Member"
    
    if not frappe.db.exists("Role Profile", default_profile):
        print(f"Default role profile '{default_profile}' does not exist, skipping chapter migration")
        return
    
    migrated_chapters = 0
    
    # Get all chapters
    chapters = frappe.get_all("Chapter", fields=["name"])
    
    for chapter in chapters:
        try:
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            
            # Only migrate if not already configured
            if not chapter_doc.default_board_role_profile:
                chapter_doc.default_board_role_profile = default_profile
                chapter_doc.save()
                migrated_chapters += 1
                print(f"✅ Migrated chapter '{chapter.name}' → '{default_profile}'")
            else:
                print(f"ℹ️  Chapter '{chapter.name}' already configured")
                
        except Exception as e:
            print(f"❌ Error migrating chapter '{chapter.name}': {str(e)}")
    
    print(f"Migrated {migrated_chapters} chapter configurations")


def test_enhanced_system():
    """Test the new enhanced role profile system"""
    
    print("\n--- Testing Enhanced System ---")
    
    # Test team system
    test_team_system()
    
    # Test chapter system  
    test_chapter_system()


def test_team_system():
    """Test enhanced team role profile system"""
    
    print("\n🧪 Testing Team System:")
    
    from verenigingen.utils.team_role_profile_manager import (
        get_team_role_profile_config,
        determine_role_profile_for_team_member,
        get_team_role_profile_mapping
    )
    
    # Test configuration reading
    test_teams = ["Kascommissie"]  # Add more teams as needed
    
    for team_name in test_teams:
        if frappe.db.exists("Team", team_name):
            print(f"\n  Testing team: {team_name}")
            
            # Test config retrieval
            config = get_team_role_profile_config(team_name)
            print(f"    Default profile: {config.get('default_profile')}")
            print(f"    Role-specific enabled: {config.get('enable_role_specific')}")
            print(f"    Role-specific profiles: {config.get('role_specific_profiles')}")
            
            # Test profile determination
            profile = determine_role_profile_for_team_member(team_name)
            print(f"    Determined profile: {profile}")
        else:
            print(f"  ⚠️  Team '{team_name}' not found")
    
    # Test mapping retrieval
    mapping = get_team_role_profile_mapping()
    print(f"\n  Available mappings: {mapping}")


def test_chapter_system():
    """Test enhanced chapter role profile system"""
    
    print("\n🧪 Testing Chapter System:")
    
    from verenigingen.utils.chapter_role_profile_manager import (
        get_chapter_role_profile_config,
        determine_role_profile_for_board_member,
        get_chapter_board_role_profile_mapping
    )
    
    # Get first few chapters for testing
    test_chapters = frappe.get_all("Chapter", fields=["name"], limit=3)
    
    for chapter in test_chapters:
        chapter_name = chapter.name
        print(f"\n  Testing chapter: {chapter_name}")
        
        # Test config retrieval
        config = get_chapter_role_profile_config(chapter_name)
        print(f"    Default profile: {config.get('default_profile')}")
        print(f"    Role-specific enabled: {config.get('enable_role_specific')}")
        print(f"    Role-specific profiles: {config.get('role_specific_profiles')}")
        
        # Test profile determination
        profile = determine_role_profile_for_board_member(chapter_name)
        print(f"    Determined profile: {profile}")
    
    # Test mapping retrieval
    mapping = get_chapter_board_role_profile_mapping()
    print(f"\n  Available mappings: {len(mapping)} chapters configured")


def setup_example_configurations():
    """Set up example configurations to demonstrate the new system"""
    
    print("\n--- Setting Up Example Configurations ---")
    
    # Example: Configure a team with role-specific profiles
    setup_example_team()
    
    # Example: Configure a chapter with role-specific profiles
    setup_example_chapter()


def setup_example_team():
    """Set up an example team with role-specific configurations"""
    
    example_team_name = "Communications Team"  # Example team
    
    if frappe.db.exists("Team", example_team_name):
        try:
            team_doc = frappe.get_doc("Team", example_team_name)
            
            # Set default profile
            team_doc.default_role_profile = "Verenigingen Volunteer"
            
            # Enable role-specific profiles
            team_doc.enable_role_specific_profiles = 1
            
            # Clear existing role-specific profiles
            team_doc.role_specific_profiles = []
            
            # Add role-specific assignments (if roles exist)
            if frappe.db.exists("Team Role", "Team Lead"):
                team_doc.append("role_specific_profiles", {
                    "team_role": "Team Lead",
                    "role_profile": "Verenigingen Team Leader",
                    "description": "Team leaders get enhanced permissions"
                })
            
            if frappe.db.exists("Team Role", "Communications Manager"):
                team_doc.append("role_specific_profiles", {
                    "team_role": "Communications Manager", 
                    "role_profile": "Verenigingen Communications Officer",
                    "description": "Communications managers get full communications access"
                })
            
            team_doc.save()
            print(f"✅ Set up example configuration for team '{example_team_name}'")
            
        except Exception as e:
            print(f"❌ Error setting up example team: {str(e)}")
    else:
        print(f"ℹ️  Example team '{example_team_name}' does not exist")


def setup_example_chapter():
    """Set up an example chapter with role-specific configurations"""
    
    # Get first chapter for example
    chapters = frappe.get_all("Chapter", fields=["name"], limit=1)
    if not chapters:
        print("ℹ️  No chapters available for example setup")
        return
    
    example_chapter_name = chapters[0].name
    
    try:
        chapter_doc = frappe.get_doc("Chapter", example_chapter_name)
        
        # Set default profile
        chapter_doc.default_board_role_profile = "Verenigingen Chapter Board Member"
        
        # Enable role-specific profiles
        chapter_doc.enable_board_role_specific_profiles = 1
        
        # Clear existing role-specific profiles
        chapter_doc.board_role_specific_profiles = []
        
        # Add role-specific assignments (if roles exist)
        if frappe.db.exists("Chapter Role", "Chapter Treasurer"):
            chapter_doc.append("board_role_specific_profiles", {
                "chapter_role": "Chapter Treasurer",
                "role_profile": "Verenigingen Treasurer",
                "description": "Chapter treasurers get financial permissions"
            })
        
        if frappe.db.exists("Chapter Role", "Chapter Secretary"):
            chapter_doc.append("board_role_specific_profiles", {
                "chapter_role": "Chapter Secretary",
                "role_profile": "Verenigingen Staff",
                "description": "Chapter secretaries get administrative permissions"
            })
        
        chapter_doc.save()
        print(f"✅ Set up example configuration for chapter '{example_chapter_name}'")
        
    except Exception as e:
        print(f"❌ Error setting up example chapter: {str(e)}")


def generate_migration_report():
    """Generate a report on the current state of role profile configurations"""
    
    print("\n=== ROLE PROFILE CONFIGURATION REPORT ===")
    
    # Teams report
    print("\n--- TEAMS ---")
    teams = frappe.get_all("Team", fields=["name", "default_role_profile", "enable_role_specific_profiles"])
    
    configured_teams = 0
    role_specific_teams = 0
    
    for team in teams:
        if team.default_role_profile:
            configured_teams += 1
        if team.enable_role_specific_profiles:
            role_specific_teams += 1
        
        status = "✅" if team.default_role_profile else "⚠️"
        role_specific_status = "🎯" if team.enable_role_specific_profiles else ""
        print(f"  {status} {team.name}: {team.default_role_profile or 'Not configured'} {role_specific_status}")
    
    print(f"\nTeam Summary: {configured_teams}/{len(teams)} configured, {role_specific_teams} with role-specific profiles")
    
    # Chapters report
    print("\n--- CHAPTERS ---")
    chapters = frappe.get_all("Chapter", fields=["name", "default_board_role_profile", "enable_board_role_specific_profiles"])
    
    configured_chapters = 0
    role_specific_chapters = 0
    
    for chapter in chapters:
        if chapter.default_board_role_profile:
            configured_chapters += 1
        if chapter.enable_board_role_specific_profiles:
            role_specific_chapters += 1
        
        status = "✅" if chapter.default_board_role_profile else "⚠️"
        role_specific_status = "🎯" if chapter.enable_board_role_specific_profiles else ""
        print(f"  {status} {chapter.name}: {chapter.default_board_role_profile or 'Not configured'} {role_specific_status}")
    
    print(f"\nChapter Summary: {configured_chapters}/{len(chapters)} configured, {role_specific_chapters} with role-specific profiles")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "report":
            frappe.init()
            frappe.connect()
            generate_migration_report()
            frappe.destroy()
        elif sys.argv[1] == "examples":
            frappe.init()
            frappe.connect()
            setup_example_configurations()
            frappe.db.commit()
            frappe.destroy()
        elif sys.argv[1] == "test":
            frappe.init()
            frappe.connect()
            test_enhanced_system()
            frappe.destroy()
    else:
        print("Usage: python migrate_role_profile_configuration.py [report|examples|test]")
        print("")
        print("The role profile system now requires manual configuration.")
        print("Run with 'examples' to set up sample configurations.")
        print("Run with 'test' to validate current configurations.")
        print("Run with 'report' to see current configuration status.")
        print("")
        setup_clean_system()