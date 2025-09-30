#!/usr/bin/env python3
"""
Role Profile Database Configuration Validator
============================================

This script validates that existing teams and chapters have proper role profile 
configuration and provides automated fixes for unconfigured entities.

Run this after the role profile system refactoring to ensure all entities
work with the new database-driven configuration system.

Usage:
    bench --site dev.veganisme.net run-python-script scripts/setup/validate_role_profile_db_config.py

Author: Verenigingen Development Team  
Date: 2025-08-26
"""

import frappe
from typing import Dict, List, Tuple


def validate_system_requirements() -> Tuple[bool, List[str]]:
    """Validate that required DocTypes and Role Profiles exist"""
    issues = []
    
    # Check required DocTypes exist
    required_doctypes = [
        "Team", "Chapter", "Role Profile", 
        "Team Role Profile Assignment", "Chapter Role Profile Mapping"
    ]
    
    for doctype in required_doctypes:
        if not frappe.db.exists("DocType", doctype):
            issues.append(f"Missing DocType: {doctype}")
    
    # Check common role profiles exist  
    common_profiles = [
        "Verenigingen Volunteer",
        "Verenigingen Chapter Board Member",
        "Verenigingen Treasurer"
    ]
    
    existing_profiles = frappe.get_all("Role Profile", fields=["name"])
    existing_profile_names = [p.name for p in existing_profiles]
    
    for profile in common_profiles:
        if profile not in existing_profile_names:
            issues.append(f"Missing Role Profile: {profile}")
    
    return len(issues) == 0, issues


def get_team_configuration_status() -> Dict:
    """Get current team role profile configuration status"""
    teams = frappe.get_all("Team", 
        fields=["name", "team_name", "default_role_profile", "enable_role_specific_profiles", "status"],
        filters={"status": "Active"}
    )
    
    status = {
        "total_teams": len(teams),
        "configured_teams": 0,
        "unconfigured_teams": [],
        "role_specific_teams": 0
    }
    
    for team in teams:
        if team.default_role_profile:
            status["configured_teams"] += 1
            if team.enable_role_specific_profiles:
                status["role_specific_teams"] += 1
        else:
            status["unconfigured_teams"].append({
                "name": team.name,
                "team_name": team.team_name,
                "suggested_profile": suggest_team_profile(team.team_name)
            })
    
    return status


def get_chapter_configuration_status() -> Dict:
    """Get current chapter role profile configuration status"""
    chapters = frappe.get_all("Chapter",
        fields=["name", "chapter_name", "default_board_role_profile", "enable_board_role_specific_profiles", "status"],
        filters={"status": "Active"}
    )
    
    status = {
        "total_chapters": len(chapters),
        "configured_chapters": 0,
        "unconfigured_chapters": [],
        "role_specific_chapters": 0
    }
    
    for chapter in chapters:
        if chapter.default_board_role_profile:
            status["configured_chapters"] += 1
            if chapter.enable_board_role_specific_profiles:
                status["role_specific_chapters"] += 1
        else:
            status["unconfigured_chapters"].append({
                "name": chapter.name,
                "chapter_name": chapter.chapter_name,
                "suggested_profile": "Verenigingen Chapter Board Member"  # Default for chapters
            })
    
    return status


def suggest_team_profile(team_name: str) -> str:
    """Suggest appropriate role profile based on team name"""
    name_lower = team_name.lower()
    
    # Smart suggestions based on team function
    if any(keyword in name_lower for keyword in ["kas", "treasury", "finance", "treasurer"]):
        return "Verenigingen Treasurer"
    elif any(keyword in name_lower for keyword in ["board", "bestuur", "governance"]):
        return "Verenigingen Chapter Board Member"
    else:
        return "Verenigingen Volunteer"  # Default for most teams


def configure_unconfigured_teams(unconfigured_teams: List[Dict]) -> Tuple[int, int]:
    """Configure teams that lack role profile settings"""
    success_count = 0
    failure_count = 0
    
    for team_info in unconfigured_teams:
        try:
            team_doc = frappe.get_doc("Team", team_info["name"])
            team_doc.default_role_profile = team_info["suggested_profile"]
            team_doc.enable_role_specific_profiles = 0  # Start simple
            team_doc.save()
            
            print(f"✅ Configured team '{team_info['team_name']}' → '{team_info['suggested_profile']}'")
            success_count += 1
            
        except Exception as e:
            print(f"❌ Error configuring team '{team_info['team_name']}': {str(e)}")
            failure_count += 1
    
    return success_count, failure_count


def configure_unconfigured_chapters(unconfigured_chapters: List[Dict]) -> Tuple[int, int]:
    """Configure chapters that lack role profile settings"""
    success_count = 0
    failure_count = 0
    
    for chapter_info in unconfigured_chapters:
        try:
            chapter_doc = frappe.get_doc("Chapter", chapter_info["name"])
            chapter_doc.default_board_role_profile = chapter_info["suggested_profile"]
            chapter_doc.enable_board_role_specific_profiles = 0  # Start simple
            chapter_doc.save()
            
            print(f"✅ Configured chapter '{chapter_info['chapter_name']}' → '{chapter_info['suggested_profile']}'")
            success_count += 1
            
        except Exception as e:
            print(f"❌ Error configuring chapter '{chapter_info['chapter_name']}': {str(e)}")
            failure_count += 1
    
    return success_count, failure_count


def test_new_api_functionality():
    """Test that the new role profile API works correctly"""
    from verenigingen.utils.team_role_profile_manager import (
        get_team_role_profile_mapping,
        determine_role_profile_for_team_member
    )
    from verenigingen.utils.chapter_role_profile_manager import (
        get_chapter_board_role_profile_mapping,
        determine_role_profile_for_board_member
    )
    
    print("\\n=== TESTING NEW API FUNCTIONALITY ===")
    
    try:
        # Test team API
        team_mapping = get_team_role_profile_mapping()
        print(f"✅ Team mapping API working: Found {len(team_mapping)} configured teams")
        
        # Test chapter API
        chapter_mapping = get_chapter_board_role_profile_mapping()
        print(f"✅ Chapter mapping API working: Found {len(chapter_mapping)} configured chapters")
        
        # Test profile determination for existing entities
        if team_mapping:
            first_team = list(team_mapping.keys())[0]
            profile = determine_role_profile_for_team_member(first_team)
            print(f"✅ Team profile determination working: {first_team} → {profile}")
        
        if chapter_mapping:
            first_chapter = list(chapter_mapping.keys())[0]
            profile = determine_role_profile_for_board_member(first_chapter)
            print(f"✅ Chapter profile determination working: {first_chapter} → {profile}")
            
        print("✅ All API tests passed!")
        return True
        
    except Exception as e:
        print(f"❌ API test failed: {str(e)}")
        return False


def main():
    """Main validation and configuration function"""
    print("🔍 Role Profile Database Configuration Validator")
    print("=" * 55)
    
    # 1. Validate system requirements
    print("\\n1. Checking system requirements...")
    requirements_ok, issues = validate_system_requirements()
    
    if not requirements_ok:
        print("❌ SYSTEM REQUIREMENTS NOT MET:")
        for issue in issues:
            print(f"   • {issue}")
        print("\\nPlease run 'bench migrate' first to ensure all required components exist.")
        return 1
    
    print("✅ System requirements satisfied")
    
    # 2. Check current configuration status
    print("\\n2. Analyzing current configuration...")
    team_status = get_team_configuration_status()
    chapter_status = get_chapter_configuration_status()
    
    print(f"\\n--- TEAMS ---")
    print(f"Total: {team_status['total_teams']}, Configured: {team_status['configured_teams']}, Unconfigured: {len(team_status['unconfigured_teams'])}")
    
    print(f"\\n--- CHAPTERS ---") 
    print(f"Total: {chapter_status['total_chapters']}, Configured: {chapter_status['configured_chapters']}, Unconfigured: {len(chapter_status['unconfigured_chapters'])}")
    
    # 3. Configure unconfigured entities
    total_unconfigured = len(team_status["unconfigured_teams"]) + len(chapter_status["unconfigured_chapters"])
    
    if total_unconfigured == 0:
        print("\\n✅ All entities are already configured!")
    else:
        print(f"\\n3. Configuring {total_unconfigured} unconfigured entities...")
        
        team_success, team_failure = configure_unconfigured_teams(team_status["unconfigured_teams"])
        chapter_success, chapter_failure = configure_unconfigured_chapters(chapter_status["unconfigured_chapters"])
        
        total_success = team_success + chapter_success
        total_failure = team_failure + chapter_failure
        
        print(f"\\n📊 Configuration Results:")
        print(f"   Successfully configured: {total_success}")
        print(f"   Failed to configure: {total_failure}")
        
        if total_failure > 0:
            print("⚠️  Some configurations failed - please review manually")
            return 1
    
    # 4. Test new API functionality
    print("\\n4. Testing new role profile API...")
    if not test_new_api_functionality():
        return 1
    
    # 5. Final validation
    print("\\n🎉 DATABASE CONFIGURATION VALIDATION COMPLETE!")
    print("\\n✅ All teams and chapters now have proper role profile configuration")
    print("✅ New database-driven role profile system is fully operational")
    print("\\n📋 Summary:")
    print(f"   • Teams configured: {team_status['configured_teams'] + len(team_status['unconfigured_teams'])}")
    print(f"   • Chapters configured: {chapter_status['configured_chapters'] + len(chapter_status['unconfigured_chapters'])}")
    print("   • API functionality verified")
    
    return 0


if __name__ == "__main__":
    # This script is designed to be run via bench run-python-script
    try:
        exit_code = main()
        if exit_code != 0:
            frappe.db.rollback()
        else:
            frappe.db.commit()
    except Exception as e:
        print(f"\\n❌ Validation failed: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        frappe.db.rollback()