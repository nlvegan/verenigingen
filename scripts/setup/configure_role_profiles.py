#!/usr/bin/env python3

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
"""
Role Profile Configuration Setup Script
=======================================

This script configures existing teams and chapters with default role profiles
to ensure the new database-driven role profile system works correctly.

Usage:
    python scripts/setup/configure_role_profiles.py

The script will:
1. Check which teams/chapters lack role profile configuration
2. Provide recommended role profile assignments
3. Allow batch configuration of entities

Author: Verenigingen Development Team
Date: 2025-08-26
"""

import sys
from typing import Dict, List, Tuple

import frappe


def check_system_requirements() -> Tuple[bool, List[str]]:
    """Check if the system has the required DocTypes and Role Profiles"""
    issues = []
    
    # Check required DocTypes exist
    required_doctypes = [
        "Team", "Chapter", "Role Profile", 
        "Team Role Profile Assignment", "Chapter Role Profile Mapping"
    ]
    
    for doctype in required_doctypes:
        if not DocumentExistenceValidator.check_document_exists("DocType", doctype):
            issues.append(f"Missing DocType: {doctype}")
    
    # Check common role profiles exist
    common_profiles = [
        "Verenigingen Volunteer",
        "Verenigingen Board Member", 
        "Verenigingen Treasurer",
        "Verenigingen Team Leader"
    ]
    
    for profile in common_profiles:
        if not DocumentExistenceValidator.check_document_exists("Role Profile", profile):
            issues.append(f"Missing Role Profile: {profile}")
    
    return len(issues) == 0, issues


def analyze_team_configuration() -> Dict:
    """Analyze current team role profile configuration status"""
    teams = frappe.get_all("Team", 
        fields=["name", "team_name", "default_role_profile", "enable_role_specific_profiles", "status"],
        filters={"status": "Active"}
    )
    
    analysis = {
        "total_teams": len(teams),
        "configured_teams": 0,
        "unconfigured_teams": [],
        "role_specific_teams": 0
    }
    
    for team in teams:
        if team.default_role_profile:
            analysis["configured_teams"] += 1
            if team.enable_role_specific_profiles:
                analysis["role_specific_teams"] += 1
        else:
            analysis["unconfigured_teams"].append({
                "name": team.name,
                "team_name": team.team_name,
                "suggested_profile": suggest_team_role_profile(team.team_name)
            })
    
    return analysis


def analyze_chapter_configuration() -> Dict:
    """Analyze current chapter role profile configuration status"""
    chapters = frappe.get_all("Chapter",
        fields=["name", "chapter_name", "default_board_role_profile", "enable_board_role_specific_profiles", "status"],
        filters={"status": "Active"}
    )
    
    analysis = {
        "total_chapters": len(chapters),
        "configured_chapters": 0,
        "unconfigured_chapters": [],
        "role_specific_chapters": 0
    }
    
    for chapter in chapters:
        if chapter.default_board_role_profile:
            analysis["configured_chapters"] += 1
            if chapter.enable_board_role_specific_profiles:
                analysis["role_specific_chapters"] += 1
        else:
            analysis["unconfigured_chapters"].append({
                "name": chapter.name,
                "chapter_name": chapter.chapter_name,
                "suggested_profile": suggest_chapter_role_profile(chapter.chapter_name)
            })
    
    return analysis


def suggest_team_role_profile(team_name: str) -> str:
    """Suggest a role profile for a team based on its name and function"""
    name_lower = team_name.lower()
    
    # Smart suggestions based on team function
    if any(keyword in name_lower for keyword in ["kas", "treasury", "finance", "treasurer"]):
        return "Verenigingen Treasurer"
    elif any(keyword in name_lower for keyword in ["board", "bestuur", "governance"]):
        return "Verenigingen Board Member"
    elif any(keyword in name_lower for keyword in ["lead", "manager", "head", "coordinator"]):
        return "Verenigingen Team Leader"
    else:
        return "Verenigingen Volunteer"  # Default for most teams


def suggest_chapter_role_profile(chapter_name: str) -> str:
    """Suggest a role profile for chapter board members"""
    # Most chapter board members should have board permissions
    return "Verenigingen Board Member"


def configure_team(team_name: str, role_profile: str, enable_role_specific: bool = False) -> bool:
    """Configure a team with role profile settings"""
    try:
        team_doc = frappe.get_doc("Team", team_name)
        team_doc.default_role_profile = role_profile
        team_doc.enable_role_specific_profiles = 1 if enable_role_specific else 0
        team_doc.save()
        
        print(f"✅ Configured team '{team_doc.team_name}' with role profile '{role_profile}'")
        return True
        
    except Exception as e:
        print(f"❌ Error configuring team '{team_name}': {str(e)}")
        return False


def configure_chapter(chapter_name: str, role_profile: str, enable_role_specific: bool = False) -> bool:
    """Configure a chapter with role profile settings"""
    try:
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.default_board_role_profile = role_profile
        chapter_doc.enable_board_role_specific_profiles = 1 if enable_role_specific else 0
        chapter_doc.save()
        
        print(f"✅ Configured chapter '{chapter_doc.chapter_name}' with role profile '{role_profile}'")
        return True
        
    except Exception as e:
        print(f"❌ Error configuring chapter '{chapter_name}': {str(e)}")
        return False


def batch_configure_teams(team_configs: List[Dict]) -> Tuple[int, int]:
    """Configure multiple teams in batch"""
    success_count = 0
    failure_count = 0
    
    for config in team_configs:
        if configure_team(
            team_name=config["name"],
            role_profile=config["role_profile"],
            enable_role_specific=config.get("enable_role_specific", False)
        ):
            success_count += 1
        else:
            failure_count += 1
    
    return success_count, failure_count


def batch_configure_chapters(chapter_configs: List[Dict]) -> Tuple[int, int]:
    """Configure multiple chapters in batch"""
    success_count = 0
    failure_count = 0
    
    for config in chapter_configs:
        if configure_chapter(
            chapter_name=config["name"],
            role_profile=config["role_profile"],
            enable_role_specific=config.get("enable_role_specific", False)
        ):
            success_count += 1
        else:
            failure_count += 1
    
    return success_count, failure_count


def apply_suggested_configurations() -> Dict:
    """Apply suggested configurations to all unconfigured entities"""
    print("🔧 Applying suggested configurations...")
    
    team_analysis = analyze_team_configuration()
    chapter_analysis = analyze_chapter_configuration()
    
    results = {
        "teams": {"success": 0, "failure": 0},
        "chapters": {"success": 0, "failure": 0}
    }
    
    # Configure teams
    if team_analysis["unconfigured_teams"]:
        team_configs = [{
            "name": team["name"],
            "role_profile": team["suggested_profile"],
            "enable_role_specific": False  # Start with simple configuration
        } for team in team_analysis["unconfigured_teams"]]
        
        success, failure = batch_configure_teams(team_configs)
        results["teams"]["success"] = success
        results["teams"]["failure"] = failure
    
    # Configure chapters
    if chapter_analysis["unconfigured_chapters"]:
        chapter_configs = [{
            "name": chapter["name"],
            "role_profile": chapter["suggested_profile"],
            "enable_role_specific": False  # Start with simple configuration
        } for chapter in chapter_analysis["unconfigured_chapters"]]
        
        success, failure = batch_configure_chapters(chapter_configs)
        results["chapters"]["success"] = success
        results["chapters"]["failure"] = failure
    
    return results


def print_configuration_report():
    """Print detailed configuration status report"""
    print("=" * 70)
    print("ROLE PROFILE CONFIGURATION REPORT")
    print("=" * 70)
    
    # System requirements check
    requirements_ok, issues = check_system_requirements()
    if not requirements_ok:
        print("\\n❌ SYSTEM REQUIREMENTS NOT MET:")
        for issue in issues:
            print(f"   • {issue}")
        print("\\nPlease run 'bench migrate' to ensure all required DocTypes and Role Profiles exist.")
        return
    
    print("\\n✅ System requirements satisfied")
    
    # Team analysis
    team_analysis = analyze_team_configuration()
    print(f"\\n--- TEAMS ---")
    print(f"Total active teams: {team_analysis['total_teams']}")
    print(f"Configured teams: {team_analysis['configured_teams']}")
    print(f"Unconfigured teams: {len(team_analysis['unconfigured_teams'])}")
    print(f"Teams with role-specific profiles: {team_analysis['role_specific_teams']}")
    
    if team_analysis["unconfigured_teams"]:
        print("\\nUnconfigured teams with suggestions:")
        for team in team_analysis["unconfigured_teams"][:5]:  # Show first 5
            print(f"   • {team['team_name']} → {team['suggested_profile']}")
        if len(team_analysis["unconfigured_teams"]) > 5:
            print(f"   ... and {len(team_analysis['unconfigured_teams']) - 5} more")
    
    # Chapter analysis
    chapter_analysis = analyze_chapter_configuration()
    print(f"\\n--- CHAPTERS ---")
    print(f"Total active chapters: {chapter_analysis['total_chapters']}")
    print(f"Configured chapters: {chapter_analysis['configured_chapters']}")
    print(f"Unconfigured chapters: {len(chapter_analysis['unconfigured_chapters'])}")
    print(f"Chapters with role-specific profiles: {chapter_analysis['role_specific_chapters']}")
    
    if chapter_analysis["unconfigured_chapters"]:
        print("\\nUnconfigured chapters with suggestions:")
        for chapter in chapter_analysis["unconfigured_chapters"][:5]:  # Show first 5
            print(f"   • {chapter['chapter_name']} → {chapter['suggested_profile']}")
        if len(chapter_analysis["unconfigured_chapters"]) > 5:
            print(f"   ... and {len(chapter_analysis['unconfigured_chapters']) - 5} more")


def main():
    """Main configuration function"""
    print("🔧 Role Profile Configuration Setup")
    print("=" * 50)
    
    # Initialize Frappe
    try:
        frappe.init(site="dev.veganisme.net")
        frappe.connect()
    except Exception as e:
        print(f"❌ Error connecting to Frappe: {str(e)}")
        return 1
    
    try:
        # Print current status
        print_configuration_report()
        
        # Check if configuration is needed
        team_analysis = analyze_team_configuration()
        chapter_analysis = analyze_chapter_configuration()
        
        total_unconfigured = len(team_analysis["unconfigured_teams"]) + len(chapter_analysis["unconfigured_chapters"])
        
        if total_unconfigured == 0:
            print("\\n🎉 All entities are already configured!")
            return 0
        
        print(f"\\n📋 Found {total_unconfigured} entities that need configuration")
        print("\\nOptions:")
        print("  1. Apply suggested configurations automatically")
        print("  2. Show detailed recommendations and exit")
        print("  3. Exit without changes")
        
        # For automation, default to option 1
        choice = "1"  # Can be made interactive if needed
        
        if choice == "1":
            print("\\n🚀 Applying suggested configurations...")
            results = apply_suggested_configurations()
            
            total_success = results["teams"]["success"] + results["chapters"]["success"]
            total_failure = results["teams"]["failure"] + results["chapters"]["failure"]
            
            print(f"\\n📊 Configuration Results:")
            print(f"   • Successfully configured: {total_success}")
            print(f"   • Failed to configure: {total_failure}")
            
            if total_failure == 0:
                print("\\n🎉 All entities configured successfully!")
                frappe.db.commit()
            else:
                print("\\n⚠️  Some configurations failed. Please review and fix manually.")
                frappe.db.rollback()
                return 1
        
        elif choice == "2":
            print("\\n📋 Detailed recommendations shown above. Run with option 1 to apply.")
        
        else:
            print("\\n👋 Exiting without changes")
        
        return 0
        
    except Exception as e:
        print(f"\\n❌ Configuration failed: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        frappe.db.rollback()
        return 1
        
    finally:
        try:
            frappe.destroy()
        except:
            pass


if __name__ == "__main__":
    sys.exit(main())