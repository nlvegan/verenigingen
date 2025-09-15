#!/usr/bin/env python3
"""
Context Validators for Security Level Mappings

This module provides context-specific validation methods for the security framework,
solving complex access control scenarios like volunteer expense submissions,
chapter-specific permissions, and self-service operations.

Author: Claude Code Assistant
Date: September 15, 2025
"""

import logging
from typing import Any, Callable, Dict, Optional

import frappe

logger = logging.getLogger(__name__)


def validate_self_service_access(user: str, operation_data: Dict[str, Any]) -> bool:
    """
    Validate that user can only perform self-service operations on their own data

    Solves: Volunteers can submit their own expenses but not access others' data
    """
    try:
        # Get the target member/user from operation data
        target_user = operation_data.get("user_id")
        target_member = operation_data.get("member_id")
        target_party = operation_data.get("party")

        # Direct user match
        if target_user and target_user == user:
            return True

        # Member record match - check if user is linked to this member
        if target_member:
            user_member = get_user_member_record(user)
            if user_member and user_member == target_member:
                return True

        # Party match (for payment entries, invoices)
        if target_party:
            user_member = get_user_member_record(user)
            if user_member and user_member == target_party:
                return True

        return False

    except Exception as e:
        logger.error(f"Error in self-service validation for user {user}: {e}")
        return False


def validate_chapter_specific_access(user: str, operation_data: Dict[str, Any]) -> bool:
    """
    Validate chapter-specific access - board members can only access their chapter data

    Solves: Chapter board members can approve expenses for their chapter only
    """
    try:
        target_chapter = operation_data.get("chapter_id")
        member_chapter = operation_data.get("member_chapter")

        if not (target_chapter or member_chapter):
            # No chapter context, allow access
            return True

        # Get user's board member chapters
        user_board_chapters = get_user_board_chapters(user)

        # Check direct chapter match
        if target_chapter and target_chapter in user_board_chapters:
            return True

        # Check member's chapter match (for approving member expenses)
        if member_chapter and member_chapter in user_board_chapters:
            return True

        return False

    except Exception as e:
        logger.error(f"Error in chapter-specific validation for user {user}: {e}")
        return False


def validate_financial_threshold_access(user: str, operation_data: Dict[str, Any]) -> bool:
    """
    Validate financial operations based on amount thresholds and user role

    Solves: Different approval limits for different roles
    """
    try:
        amount = float(operation_data.get("amount", 0))
        operation_type = operation_data.get("operation_type", "")

        # Get user's financial approval limits
        approval_limits = get_user_financial_limits(user)

        # Check if amount exceeds user's limit for this operation type
        limit_key = f"{operation_type}_limit"
        user_limit = approval_limits.get(limit_key, approval_limits.get("default_limit", 0))

        return amount <= user_limit

    except Exception as e:
        logger.error(f"Error in financial threshold validation for user {user}: {e}")
        return False


def validate_volunteer_operations_access(user: str, operation_data: Dict[str, Any]) -> bool:
    """
    Validate volunteer-specific operations with context awareness

    Solves: Volunteers can submit expenses, join teams, but not manage other volunteers
    """
    try:
        operation_type = operation_data.get("operation_type", "")
        target_volunteer = operation_data.get("volunteer_id")

        # Self-service operations - volunteers can manage their own records
        if operation_type in ["expense_submission", "profile_update", "team_join"]:
            return validate_self_service_access(user, operation_data)

        # Team operations - check if user is team leader
        if operation_type in ["team_management", "volunteer_approval"]:
            return validate_team_leadership_access(user, operation_data)

        # Default: allow if it's their own volunteer record
        if target_volunteer:
            user_volunteer = get_user_volunteer_record(user)
            return user_volunteer == target_volunteer

        return True

    except Exception as e:
        logger.error(f"Error in volunteer operations validation for user {user}: {e}")
        return False


def validate_team_leadership_access(user: str, operation_data: Dict[str, Any]) -> bool:
    """
    Validate team leadership operations

    Solves: Team leaders can manage their team members but not others
    """
    try:
        target_team = operation_data.get("team_id")
        target_volunteer = operation_data.get("volunteer_id")

        # Get teams where user is a leader
        user_led_teams = get_user_led_teams(user)

        # Direct team match
        if target_team and target_team in user_led_teams:
            return True

        # Check if target volunteer is in user's teams
        if target_volunteer:
            volunteer_teams = get_volunteer_teams(target_volunteer)
            return any(team in user_led_teams for team in volunteer_teams)

        return False

    except Exception as e:
        logger.error(f"Error in team leadership validation for user {user}: {e}")
        return False


def validate_kascommissie_access(user: str, operation_data: Dict[str, Any]) -> bool:
    """
    Validate Kascommissie (audit committee) specific access

    Solves: Kascommissie can audit financial records but not create/modify them
    """
    try:
        operation_type = operation_data.get("operation_type", "")

        # Kascommissie can read financial data but not modify
        if operation_type in ["audit", "financial_review", "compliance_check"]:
            return True

        if operation_type in ["create", "update", "delete", "approve"]:
            return False

        # Default to read-only access
        return operation_type in ["read", "export", "report"]

    except Exception as e:
        logger.error(f"Error in kascommissie validation for user {user}: {e}")
        return False


# Helper functions


def get_user_member_record(user: str) -> Optional[str]:
    """Get the member record linked to a user"""
    try:
        member = frappe.db.get_value("Member", {"user_id": user}, "name")
        return member
    except Exception as e:
        logger.error(f"Error getting member record for user {user}: {e}")
        return None


def get_user_board_chapters(user: str) -> list:
    """Get chapters where user is a board member"""
    try:
        member = get_user_member_record(user)
        if not member:
            return []

        chapters = frappe.get_all(
            "Chapter Board Member", filters={"member": member, "status": "Active"}, fields=["chapter"]
        )

        return [chapter.chapter for chapter in chapters]

    except Exception as e:
        logger.error(f"Error getting board chapters for user {user}: {e}")
        return []


def get_user_financial_limits(user: str) -> Dict[str, float]:
    """Get financial approval limits for user based on their roles"""
    try:
        # Define default limits by role profile
        role_limits = {
            "Verenigingen Treasurer": {"default_limit": 50000, "expense_limit": 10000},
            "Verenigingen Manager": {"default_limit": 25000, "expense_limit": 5000},
            "Verenigingen Board Member": {"default_limit": 5000, "expense_limit": 1000},
            "Verenigingen Team Leader": {"default_limit": 1000, "expense_limit": 500},
            "Verenigingen Volunteer": {"default_limit": 500, "expense_limit": 200},
            "Verenigingen Member": {"default_limit": 100, "expense_limit": 100},
        }

        # Get user's role profiles
        user_doc = frappe.get_doc("User", user)
        user_limits = {"default_limit": 0}

        # Get highest limits from all role profiles
        for role_profile in user_doc.get("role_profiles", []):
            profile_limits = role_limits.get(role_profile.role_profile, {})
            for limit_type, limit_value in profile_limits.items():
                current_limit = user_limits.get(limit_type, 0)
                user_limits[limit_type] = max(current_limit, limit_value)

        return user_limits

    except Exception as e:
        logger.error(f"Error getting financial limits for user {user}: {e}")
        return {"default_limit": 0}


def get_user_volunteer_record(user: str) -> Optional[str]:
    """Get volunteer record linked to user"""
    try:
        member = get_user_member_record(user)
        if not member:
            return None

        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        return volunteer

    except Exception as e:
        logger.error(f"Error getting volunteer record for user {user}: {e}")
        return None


def get_user_led_teams(user: str) -> list:
    """Get teams where user is a leader"""
    try:
        volunteer = get_user_volunteer_record(user)
        if not volunteer:
            return []

        teams = frappe.get_all(
            "Volunteer Team Member",
            filters={"volunteer": volunteer, "role": ["in", ["Team Leader", "Project Manager"]]},
            fields=["parent"],
        )

        return [team.parent for team in teams]

    except Exception as e:
        logger.error(f"Error getting led teams for user {user}: {e}")
        return []


def get_volunteer_teams(volunteer: str) -> list:
    """Get teams that a volunteer belongs to"""
    try:
        teams = frappe.get_all("Volunteer Team Member", filters={"volunteer": volunteer}, fields=["parent"])

        return [team.parent for team in teams]

    except Exception as e:
        logger.error(f"Error getting teams for volunteer {volunteer}: {e}")
        return []


# Context validator registry
CONTEXT_VALIDATORS: Dict[str, Callable] = {
    "validate_self_service_access": validate_self_service_access,
    "validate_chapter_specific_access": validate_chapter_specific_access,
    "validate_financial_threshold_access": validate_financial_threshold_access,
    "validate_volunteer_operations_access": validate_volunteer_operations_access,
    "validate_team_leadership_access": validate_team_leadership_access,
    "validate_kascommissie_access": validate_kascommissie_access,
}


def get_context_validator(validator_name: str) -> Optional[Callable]:
    """Get a context validator function by name"""
    return CONTEXT_VALIDATORS.get(validator_name)


def list_available_validators() -> list:
    """List all available context validators"""
    return list(CONTEXT_VALIDATORS.keys())
