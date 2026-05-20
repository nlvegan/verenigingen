"""
User Role Profile Calculator

Calculates the correct role profile for a user based on their current organizational roles.
This is a ground-truth approach that derives the profile from actual assignments rather than
trying to maintain state through add/remove operations.

Priority Order (highest to lowest):
1. Special accounting roles (Treasurer, Auditor) — priority 100
2. Board roles with custom profiles — priority 80
3. Association-wide staff teams — priority 75
4. Default board member profile — priority 70
5. Team roles with custom profiles — priority 60
6. Team leader default — priority 50
7. Active Volunteer — priority 30
8. Member (default) — priority 10

Author: Verenigingen Development Team
Last Updated: 2025-10-09
"""

from datetime import timedelta
from typing import Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.constants.profile_mappings import ROLE_MODULE_MAPPING
from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api

# Profile configuration cache (5 minute TTL)
_profile_config_cache = {}
_cache_ttl = timedelta(minutes=5)


# Role profile constants (fallback defaults)
PROFILE_BOARD_MEMBER = "Verenigingen Chapter Board Member"
PROFILE_TEAM_LEADER = "Verenigingen Team Leader"
PROFILE_VOLUNTEER = "Verenigingen Volunteer"
PROFILE_MEMBER = "Verenigingen Member"

# Priority levels for profile conflicts
PRIORITY_SPECIAL_ACCOUNTING = 100  # Treasurer, Auditor with accounting access
PRIORITY_BOARD_ROLE_SPECIFIC = 80  # Board roles with custom profiles
PRIORITY_BOARD_DEFAULT = 70  # Default board member profile
PRIORITY_STAFF = 75  # Association-wide staff teams
PRIORITY_TEAM_ROLE_SPECIFIC = 60  # Team roles with custom profiles
PRIORITY_TEAM_LEADER = 50  # Default team leader profile
PRIORITY_VOLUNTEER = 30  # Active volunteer
PRIORITY_MEMBER = 10  # Default member

# Placeholder values for stub Employee records (see _ensure_employee_for_profile).
# Used only as a fallback when the linked Member has no real gender / birth_date.
# "Prefer not to say" is a Frappe-seeded gender on every install; the 1990 date
# is the same default account_creation_manager uses for its Phase 1 Employee
# insert. Keep them aligned so behaviour is identical across both code paths.
_STUB_EMPLOYEE_GENDER = "Prefer not to say"
_STUB_EMPLOYEE_DOB = "1990-01-01"


def _get_cached_chapter_profile_config(chapter_name: str) -> dict:
    """
    Get chapter profile configuration with caching.

    Returns:
        dict: {
            "default_profile": str or None,
            "enable_specific": bool,
            "specific_profiles": {role_name: profile_name}
        }
    """
    cache_key = f"chapter_profile:{chapter_name}"

    # Check cache
    if cache_key in _profile_config_cache:
        cached_data, cached_time = _profile_config_cache[cache_key]
        if now_datetime() - cached_time < _cache_ttl:
            return cached_data

    # Load from database
    try:
        chapter = frappe.get_cached_doc("Chapter", chapter_name)

        # Build specific profiles map
        specific_profiles = {}
        if chapter.enable_board_role_specific_profiles:
            for mapping in chapter.board_role_specific_profiles or []:
                if mapping.chapter_role and mapping.role_profile:
                    specific_profiles[mapping.chapter_role] = mapping.role_profile

        config = {
            "default_profile": chapter.default_board_role_profile,
            "enable_specific": bool(chapter.enable_board_role_specific_profiles),
            "specific_profiles": specific_profiles,
        }

        # Cache it
        _profile_config_cache[cache_key] = (config, now_datetime())

        return config

    except Exception as e:
        frappe.logger().warning(f"Error loading chapter profile config for {chapter_name}: {str(e)}")
        return {"default_profile": None, "enable_specific": False, "specific_profiles": {}}


def _get_cached_team_profile_config(team_name: str) -> dict:
    """
    Get team profile configuration with caching.

    Returns:
        dict: {
            "default_profile": str or None,
            "enable_specific": bool,
            "specific_profiles": {role_name: profile_name}
        }
    """
    cache_key = f"team_profile:{team_name}"

    # Check cache
    if cache_key in _profile_config_cache:
        cached_data, cached_time = _profile_config_cache[cache_key]
        if now_datetime() - cached_time < _cache_ttl:
            return cached_data

    # Load from database
    try:
        team = frappe.get_cached_doc("Team", team_name)

        # Build specific profiles map
        specific_profiles = {}
        if team.enable_role_specific_profiles:
            for mapping in team.role_specific_profiles or []:
                if mapping.team_role and mapping.role_profile:
                    specific_profiles[mapping.team_role] = mapping.role_profile

        config = {
            "default_profile": team.default_role_profile,
            "enable_specific": bool(team.enable_role_specific_profiles),
            "specific_profiles": specific_profiles,
            "is_association_wide": bool(team.is_association_wide),
        }

        # Cache it
        _profile_config_cache[cache_key] = (config, now_datetime())

        return config

    except Exception as e:
        frappe.logger().warning(f"Error loading team profile config for {team_name}: {str(e)}")
        return {
            "default_profile": None,
            "enable_specific": False,
            "specific_profiles": {},
            "is_association_wide": False,
        }


def invalidate_profile_config_cache(entity_type: str = None, entity_name: str = None):
    """
    Invalidate profile configuration cache.

    Args:
        entity_type: "chapter" or "team" (if None, clears all)
        entity_name: Specific entity name (if None, clears all of type)
    """
    if entity_name:
        # Clear specific entity
        cache_key = f"{entity_type}_profile:{entity_name}"
        _profile_config_cache.pop(cache_key, None)
    elif entity_type:
        # Clear all of type
        keys_to_remove = [k for k in _profile_config_cache.keys() if k.startswith(f"{entity_type}_profile:")]
        for key in keys_to_remove:
            _profile_config_cache.pop(key, None)
    else:
        # Clear all
        _profile_config_cache.clear()


def _create_profile_change_audit_log(
    user: str, old_profile: str, new_profile: str, old_module: str = None, new_module: str = None
):
    """
    Create audit log entry for role profile change.

    Args:
        user: User whose profile changed
        old_profile: Previous role profile (or None)
        new_profile: New role profile
        old_module: Previous module profile (or None)
        new_module: New module profile (or None)
    """
    try:
        # Format change message
        old_role_display = old_profile or "(None)"
        old_module_display = old_module or "(None)"
        new_module_display = new_module or "(None)"

        change_parts = []
        if old_profile != new_profile:
            change_parts.append(f"Role: {old_role_display} → {new_profile}")
        if old_module != new_module:
            change_parts.append(f"Module: {old_module_display} → {new_module_display}")

        change_message = "Profile updated - " + ", ".join(change_parts)

        # Create Activity Log entry
        frappe.get_doc(
            {
                "doctype": "Activity Log",
                "subject": change_message,
                "user": frappe.session.user,
                "reference_doctype": "User",
                "reference_name": user,
                "status": "Success",
                "content": change_message,
            }
        ).insert(
            ignore_permissions=True  # Security: System audit comment for role changes
        )

    except Exception as e:
        # Don't fail the profile change if audit logging fails
        frappe.logger().warning(f"Failed to create audit log for profile change: {str(e)}")


def calculate_user_role_profile(user: str) -> Optional[str]:
    """
    Calculate the correct role profile for a user based on their current roles.

    This is a pure function that determines what profile the user SHOULD have
    based on their current organizational assignments and configured profiles.

    Args:
        user: User email/ID

    Returns:
        str: Role profile name, or None if user is not a member

    Priority Order (highest to lowest):
        1. Special accounting roles (Treasurer, Auditor) - Priority 100
        2. Board roles with custom profiles - Priority 80
        3. Association-wide staff teams - Priority 75
        4. Default board member profile - Priority 70
        5. Team roles with custom profiles - Priority 60
        6. Team leader default - Priority 50
        7. Active volunteer - Priority 30
        8. Member (default) - Priority 10
    """
    if not user or user == "Guest":
        return None

    # Get member record for this user
    member = frappe.db.get_value("Member", {"user": user}, "name")
    if not member:
        return None

    # Collect all applicable profiles with their priorities
    profiles_with_priority = []

    # Check 1: Board positions (may have role-specific or default profiles)
    board_profiles = get_board_member_profiles(user, member)
    profiles_with_priority.extend(board_profiles)

    # Check 2: Team leadership and memberships
    team_profiles = get_team_profiles(user, member)
    profiles_with_priority.extend(team_profiles)

    # Check 3: Active volunteer (fallback)
    if is_active_volunteer(user, member):
        profiles_with_priority.append((PRIORITY_VOLUNTEER, PROFILE_VOLUNTEER))

    # Check 4: Default member (always included as lowest priority)
    profiles_with_priority.append((PRIORITY_MEMBER, PROFILE_MEMBER))

    # Return highest priority profile
    if profiles_with_priority:
        return max(profiles_with_priority, key=lambda x: x[0])[1]

    return PROFILE_MEMBER


def get_board_member_profiles(user: str, member: str) -> list:
    """
    Get all role profiles from user's board positions.

    Returns:
        list: [(priority, profile_name), ...] for all board positions
    """
    profiles = []

    try:
        # Get volunteer record for this member
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        if not volunteer:
            frappe.logger().debug(f"No volunteer record found for member {member}")
            return profiles

        # Get all active board positions
        board_positions = frappe.db.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer, "is_active": 1},
            fields=["parent", "chapter_role"],
        )

        for position in board_positions:
            try:
                # Validate chapter exists
                if not frappe.db.exists("Chapter", position.parent):
                    frappe.log_error(
                        f"Chapter {position.parent} not found for board member {volunteer}",
                        "Role Profile: Missing Chapter",
                    )
                    continue

                # Get cached chapter profile configuration
                chapter_config = _get_cached_chapter_profile_config(position.parent)

                # Check if chapter has role-specific profiles enabled
                if chapter_config["enable_specific"] and position.chapter_role:
                    # Look up role-specific profile
                    role_profile = chapter_config["specific_profiles"].get(position.chapter_role)

                    if role_profile:
                        # Validate role profile exists
                        if not frappe.db.exists("Role Profile", role_profile):
                            frappe.log_error(
                                f"Role profile '{role_profile}' configured for {position.parent} role '{position.chapter_role}' does not exist",
                                "Role Profile: Missing Profile",
                            )
                            # Fall through to default profile
                        else:
                            # Determine priority based on role name
                            priority = get_profile_priority_for_role(position.chapter_role, role_profile)
                            profiles.append((priority, role_profile))
                            continue

                # Fall back to default board role profile
                if chapter_config["default_profile"]:
                    # Validate default profile exists
                    if not frappe.db.exists("Role Profile", chapter_config["default_profile"]):
                        frappe.log_error(
                            f"Default role profile '{chapter_config['default_profile']}' for {position.parent} does not exist",
                            "Role Profile: Missing Profile",
                        )
                        # Fall through to hardcoded default
                    else:
                        profiles.append((PRIORITY_BOARD_DEFAULT, chapter_config["default_profile"]))
                        continue

                # Ultimate fallback to hardcoded default (validate it exists)
                if frappe.db.exists("Role Profile", PROFILE_BOARD_MEMBER):
                    profiles.append((PRIORITY_BOARD_DEFAULT, PROFILE_BOARD_MEMBER))
                else:
                    frappe.log_error(
                        f"Hardcoded fallback profile '{PROFILE_BOARD_MEMBER}' does not exist - user {user} may lose board permissions",
                        "Role Profile: Critical Configuration Error",
                    )

            except Exception as e:
                frappe.log_error(
                    f"Error processing board position {position.parent} for user {user}: {str(e)}\n{frappe.get_traceback()}",
                    "Role Profile: Board Position Error",
                )
                # Continue processing other positions
                continue

    except Exception as e:
        frappe.log_error(
            f"Fatal error getting board profiles for user {user}: {str(e)}\n{frappe.get_traceback()}",
            "Role Profile: Fatal Error",
        )

    return profiles


def get_team_profiles(user: str, member: str) -> list:
    """
    Get all role profiles from user's team leadership and memberships.

    Returns:
        list: [(priority, profile_name), ...] for all team positions
    """
    profiles = []

    try:
        # Get volunteer record for this member
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")

        # Check 1: Team leadership (team_lead field)
        teams_as_leader = frappe.db.get_all(
            "Team", filters={"team_lead": user, "status": "Active"}, fields=["name", "default_role_profile"]
        )

        for team in teams_as_leader:
            if team["default_role_profile"]:
                # Validate profile exists
                if not frappe.db.exists("Role Profile", team["default_role_profile"]):
                    frappe.log_error(
                        f"Default role profile '{team['default_role_profile']}' for team {team['name']} does not exist",
                        "Role Profile: Missing Profile",
                    )
                else:
                    profiles.append((PRIORITY_TEAM_LEADER, team["default_role_profile"]))
            else:
                # Fallback to hardcoded default (validate it exists)
                if frappe.db.exists("Role Profile", PROFILE_TEAM_LEADER):
                    profiles.append((PRIORITY_TEAM_LEADER, PROFILE_TEAM_LEADER))
                else:
                    frappe.log_error(
                        f"Hardcoded fallback profile '{PROFILE_TEAM_LEADER}' does not exist - user {user} may lose team leader permissions",
                        "Role Profile: Critical Configuration Error",
                    )

        # Check 2: Team memberships (may have role-specific profiles)
        if volunteer:
            team_memberships = frappe.db.get_all(
                "Team Member",
                filters={"volunteer": volunteer, "status": "Active"},
                fields=["parent", "team_role"],
            )

            for membership in team_memberships:
                try:
                    # Validate team exists
                    if not frappe.db.exists("Team", membership.parent):
                        frappe.log_error(
                            f"Team {membership.parent} not found for team member {volunteer}",
                            "Role Profile: Missing Team",
                        )
                        continue

                    # Get cached team profile configuration
                    team_config = _get_cached_team_profile_config(membership.parent)

                    # Check if team has role-specific profiles enabled
                    if team_config["enable_specific"] and membership.team_role:
                        # Look up role-specific profile
                        role_profile = team_config["specific_profiles"].get(membership.team_role)

                        if role_profile:
                            # Validate role profile exists
                            if not frappe.db.exists("Role Profile", role_profile):
                                frappe.log_error(
                                    f"Role profile '{role_profile}' configured for {membership.parent} role '{membership.team_role}' does not exist",
                                    "Role Profile: Missing Profile",
                                )
                                # Fall through to default
                            else:
                                # Association-wide teams get higher priority
                                priority = (
                                    PRIORITY_STAFF
                                    if team_config.get("is_association_wide")
                                    else PRIORITY_TEAM_ROLE_SPECIFIC
                                )
                                profiles.append((priority, role_profile))
                                continue

                    # Fall back to default team role profile (if not already team leader)
                    # Don't double-count if user is both leader and member
                    team_leader_names = {t["name"] for t in teams_as_leader}
                    if membership.parent not in team_leader_names:
                        if team_config["default_profile"]:
                            # Validate profile exists
                            if frappe.db.exists("Role Profile", team_config["default_profile"]):
                                priority = (
                                    PRIORITY_STAFF
                                    if team_config.get("is_association_wide")
                                    else PRIORITY_TEAM_ROLE_SPECIFIC
                                )
                                profiles.append((priority, team_config["default_profile"]))
                            else:
                                frappe.log_error(
                                    f"Default role profile '{team_config['default_profile']}' for team {membership.parent} does not exist",
                                    "Role Profile: Missing Profile",
                                )

                except Exception as e:
                    frappe.log_error(
                        f"Error processing team membership {membership.parent} for user {user}: {str(e)}\n{frappe.get_traceback()}",
                        "Role Profile: Team Membership Error",
                    )
                    # Continue processing other memberships
                    continue

    except Exception as e:
        frappe.log_error(
            f"Fatal error getting team profiles for user {user}: {str(e)}\n{frappe.get_traceback()}",
            "Role Profile: Fatal Error",
        )

    return profiles


def get_profile_priority_for_role(role_name: str, profile_name: str) -> int:
    """
    Determine priority for a role based on role name and profile.

    Special accounting roles (Treasurer, Auditor, financial positions) get highest priority.

    Supports both English and Dutch keywords for maximum compatibility.

    Args:
        role_name: Board or team role name
        profile_name: Configured role profile

    Returns:
        int: Priority level
    """
    # Check for special accounting roles
    role_lower = role_name.lower() if role_name else ""
    profile_lower = profile_name.lower() if profile_name else ""

    # Dutch accounting keywords
    dutch_accounting_keywords = [
        "penningmeester",  # treasurer
        "boekhouding",  # accounting
        "financiën",  # finances
        "financieel",  # financial
        "financieel beheerder",  # financial controller
    ]

    # English accounting keywords
    english_accounting_keywords = [
        "treasurer",
        "accounting",
        "finance",
        "financial",
        "comptroller",
        "controller",
    ]

    # Check role name for accounting keywords
    if any(keyword in role_lower for keyword in dutch_accounting_keywords + english_accounting_keywords):
        return PRIORITY_SPECIAL_ACCOUNTING

    # Check profile name for accounting keywords
    if any(keyword in profile_lower for keyword in dutch_accounting_keywords + english_accounting_keywords):
        return PRIORITY_SPECIAL_ACCOUNTING

    # Default to board role specific priority
    return PRIORITY_BOARD_ROLE_SPECIFIC


def is_active_board_member(user: str, member: str) -> bool:
    """Check if user is on any active chapter board"""
    try:
        # Get volunteer record for this member
        volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
        if not volunteer:
            return False

        # Check for active board memberships
        active_board_positions = frappe.db.count(
            "Chapter Board Member", filters={"volunteer": volunteer, "is_active": 1}
        )

        return active_board_positions > 0

    except Exception as e:
        frappe.logger().warning(f"Error checking board membership for {user}: {str(e)}")
        return False


def is_team_leader(user: str, member: str) -> bool:
    """Check if user is a team leader"""
    try:
        # Check if user is team_lead in any active team
        # Note: team_lead field links directly to User, not Volunteer
        team_leader_positions = frappe.db.count("Team", filters={"team_lead": user, "status": "Active"})

        return team_leader_positions > 0

    except Exception as e:
        frappe.logger().warning(f"Error checking team leadership for {user}: {str(e)}")
        return False


def is_active_volunteer(user: str, member: str) -> bool:
    """Check if user has an active volunteer record"""
    try:
        volunteer = frappe.db.get_value(
            "Volunteer", {"member": member, "status": ["in", ["Active", "Onboarding"]]}, "name"
        )
        return bool(volunteer)

    except Exception as e:
        frappe.logger().warning(f"Error checking volunteer status for {user}: {str(e)}")
        return False


def _ensure_employee_for_profile(user: str, role_profile_name: str) -> None:
    """Create a minimal Employee record if the target profile requires the Employee role.

    ERPNext's ``validate_employee_role()`` hook (User.validate) strips Employee
    and Employee Self Service roles when no Employee record exists for the user.
    This silently undoes role profile assignments for profiles that include
    those roles (e.g. Roles.VERENIGINGEN_STAFF, "Vereinigingen Chapter Board Member").

    This function is called from ``sync_user_role_profile()`` *before*
    ``user_doc.save()`` so the Employee exists by the time the hook fires.

    Args:
        user: User email/ID
        role_profile_name: Target role profile about to be set
    """
    if not role_profile_name:
        return

    # Check if the target profile includes the Employee role
    try:
        profile_roles = {r.role for r in frappe.get_cached_doc("Role Profile", role_profile_name).roles}
    except frappe.DoesNotExistError:
        return

    if "Employee" not in profile_roles:
        return

    # Check if Employee already exists for this user
    if frappe.db.exists("Employee", {"user_id": user}):
        return

    # Get member info for the Employee record. Pull birth_date and gender too:
    # ERPNext's Employee.update_user() hook propagates emp.gender / emp.date_of_birth
    # back onto the linked User, so if the Member has real values we MUST pass
    # them through - otherwise the stub overwrites them with placeholders.
    member = frappe.db.get_value(
        "Member", {"user": user}, ["first_name", "last_name", "birth_date", "gender"], as_dict=True
    )
    if not member:
        frappe.logger().warning("Cannot create Employee for %s: no linked Member record", user)
        return

    # Get company from Vereinigingen Settings
    company = frappe.db.get_single_value("Verenigingen Settings", "company")
    if not company:
        frappe.logger().warning(
            "Cannot create Employee for %s: no company configured in Verenigingen Settings",
            user,
        )
        return

    try:
        emp = frappe.new_doc("Employee")
        emp.first_name = member.first_name
        emp.last_name = member.last_name or ""
        emp.employee_name = f"{member.first_name} {member.last_name or ''}".strip()
        emp.company = company
        emp.user_id = user
        emp.status = "Active"
        emp.date_of_joining = frappe.utils.today()
        # gender and date_of_birth are ERPNext-mandatory on Employee, AND
        # Employee.update_user() propagates them onto the linked User, so
        # we prefer the Member's real values and only fall back to placeholders
        # if missing. Placeholders match account_creation_manager.py's Phase 1
        # path - "Prefer not to say" is a Frappe-seeded gender on every install.
        emp.gender = member.get("gender") or _STUB_EMPLOYEE_GENDER
        emp.date_of_birth = member.get("birth_date") or _STUB_EMPLOYEE_DOB
        # ERPNext's Employee.on_update auto-creates a User Permission record
        # restricting the user to their own Employee record when this is 1
        # (the default). For role-profile stubs we don't want that - the
        # Phase 1 Employee insert in account_creation_manager sets this to 0
        # for the same reason. See comment there for the deeper rationale
        # (Verenigingen Staff/Admin lack User Permission create perm anyway).
        emp.create_user_permission = 0
        # Security: System-initiated Employee creation for role profile compatibility
        emp.insert(ignore_permissions=True)
        frappe.logger().info(
            "Created Employee %s for user %s (required by profile '%s')",
            emp.name,
            user,
            role_profile_name,
        )
    except frappe.DuplicateEntryError:
        # Concurrent sync created the Employee between our check and insert
        frappe.logger().debug("Employee for %s already exists (concurrent creation)", user)
    except Exception as e:
        # Surfaces as an error log entry, not just a logger line: when this
        # stub insert fails, the board member loses their Employee-bearing
        # role profile silently (the role-strip is then no longer prevented).
        frappe.logger().error("Failed to create Employee for %s: %s", user, str(e))
        frappe.log_error(
            message=f"Failed to create Employee stub for user {user} (profile {role_profile_name!r}): {e}",
            title="Role Profile Sync: Employee Stub Failed",
        )


def calculate_all_user_role_profiles(user: str) -> list[tuple[int, str]]:
    """Return the full list of applicable role profiles sorted by priority (descending).

    Unlike ``calculate_user_role_profile()`` which returns only the highest-priority
    profile, this returns all candidates. Useful for debugging and for future v16
    multi-profile support.

    Args:
        user: User email/ID

    Returns:
        List of (priority, profile_name) tuples sorted highest-priority first.
        Empty list if user is not a member.
    """
    if not user or user == "Guest":
        return []

    member = frappe.db.get_value("Member", {"user": user}, "name")
    if not member:
        return []

    profiles = []

    board_profiles = get_board_member_profiles(user, member)
    profiles.extend(board_profiles)

    team_profiles = get_team_profiles(user, member)
    profiles.extend(team_profiles)

    if is_active_volunteer(user, member):
        profiles.append((PRIORITY_VOLUNTEER, PROFILE_VOLUNTEER))

    profiles.append((PRIORITY_MEMBER, PROFILE_MEMBER))

    profiles.sort(key=lambda x: x[0], reverse=True)
    return profiles


def _has_multi_profile_support() -> bool:
    """Check if User doctype supports multiple role profiles (v16 indicator).

    Frappe v16 adds a ``role_profiles`` child table to User, allowing
    multiple profiles simultaneously. This function detects that capability.
    """
    meta = frappe.get_meta("User")
    return meta.has_field("role_profiles")


def get_user_role_profiles(user_name: str) -> list[str]:
    """Return all role profile names attached to a user, version-agnostic.

    In Frappe v15 the User has a single ``role_profile_name`` Link field.
    In v16 the field is deprecated; profiles live in a ``role_profiles``
    child table and can accumulate. Reading either directly forces every
    caller to branch on the Frappe version - this helper hides that.
    """
    if _has_multi_profile_support():
        return frappe.get_all(
            "User Role Profile",
            filters={"parent": user_name, "parenttype": "User"},
            pluck="role_profile",
        )
    single = frappe.db.get_value("User", user_name, "role_profile_name")
    return [single] if single else []


def sync_user_role_profile(user: str, dry_run: bool = False) -> dict:
    """
    Calculate and apply the correct role profile to a user.

    Args:
        user: User email/ID
        dry_run: If True, only calculate but don't apply changes

    Returns:
        dict: {
            "success": bool,
            "user": str,
            "old_profile": str,
            "new_profile": str,
            "changed": bool,
            "message": str
        }
    """
    try:
        if not frappe.db.exists("User", user):
            return {"success": False, "error": f"User {user} not found", "user": user}

        # Get current profile
        user_doc = frappe.get_doc("User", user)
        old_profile = user_doc.role_profile_name

        # Calculate correct profile
        new_profile = calculate_user_role_profile(user)

        if new_profile is None:
            return {
                "success": False,
                "error": "User is not a member",
                "user": user,
                "old_profile": old_profile,
            }

        # Get corresponding module profile. Skip if the linked Module Profile
        # record doesn't exist on this site - the role profile is the primary
        # mapping, module profile is a refinement. Failing the whole sync over
        # a missing module profile (which can happen on fresh CI sites that
        # haven't seeded the records) silently leaves the user on the wrong
        # role profile - exactly the v15 CI failure mode this PR chased.
        new_module_profile = ROLE_MODULE_MAPPING.get(new_profile)
        if new_module_profile and not frappe.db.exists("Module Profile", new_module_profile):
            frappe.logger().warning(
                f"Module Profile {new_module_profile!r} not found - "
                f"skipping module_profile update for {user}; role_profile_name still applied."
            )
            new_module_profile = None
        old_module_profile = user_doc.module_profile

        # Check if change needed
        role_changed = old_profile != new_profile
        module_changed = new_module_profile is not None and old_module_profile != new_module_profile
        changed = role_changed or module_changed

        if changed and not dry_run:
            # TODO: When Frappe v16 lands with multi-profile support,
            # use calculate_all_user_role_profiles() + _has_multi_profile_support()
            # to assign all applicable profiles instead of just the highest.

            # Ensure Employee record exists before saving User, otherwise
            # ERPNext's validate_employee_role() hook strips Employee/ESS roles
            if role_changed:
                _ensure_employee_for_profile(user, new_profile)
                # Inserting Employee triggers ERPNext hooks that modify the
                # User doc (notably adding the Employee role). Without a
                # reload, the next save raises TimestampMismatchError ("has
                # been modified after you have opened it") and silently fails
                # the entire profile sync.
                user_doc.reload()

            # Apply the changes
            if role_changed:
                user_doc.role_profile_name = new_profile
            if module_changed:
                user_doc.module_profile = new_module_profile

            user_doc.save()

            log_msg = f"Updated profiles for {user}:"
            if role_changed:
                log_msg += f" role: {old_profile} → {new_profile}"
            if module_changed:
                log_msg += f" module: {old_module_profile} → {new_module_profile}"
            frappe.logger().info(log_msg)

            # Create audit log entry
            _create_profile_change_audit_log(
                user=user,
                old_profile=old_profile,
                new_profile=new_profile,
                old_module=old_module_profile,
                new_module=new_module_profile,
            )

        return {
            "success": True,
            "user": user,
            "old_profile": old_profile,
            "new_profile": new_profile,
            "old_module_profile": old_module_profile,
            "new_module_profile": new_module_profile,
            "changed": changed,
            "role_changed": role_changed,
            "module_changed": module_changed,
            "message": (
                f"Profile {'would change' if dry_run and changed else 'changed' if changed else 'unchanged'}: role={old_profile}→{new_profile}, module={old_module_profile}→{new_module_profile}"
                if changed
                else f"Profiles correct: role={new_profile}, module={new_module_profile}"
            ),
        }

    except Exception as e:
        # Surface as Error Log too: the warning-only path lost us a
        # TimestampMismatchError regression for weeks (issue surfaced 2026-04-19
        # when the customer_group bug stopped masking it). Callers
        # (auto_sync_on_role_change, ACR's _sync_role_profile) also swallow,
        # so this is the last reachable point before silent absorption.
        frappe.logger().error(f"Error syncing role profile for {user}: {str(e)}")
        frappe.log_error(
            message=f"Error syncing role profile for {user}: {e}",
            title="Role Profile Sync Failed",
        )
        return {"success": False, "error": str(e), "user": user}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def recalculate_user_role_profile(user: str, dry_run: bool = False):
    """
    API endpoint to manually recalculate and sync a user's role profile.

    Use this when:
    - User's profile seems incorrect
    - After bulk role changes
    - For debugging/verification

    Args:
        user: User email/ID
        dry_run: If True, only show what would change without applying

    Returns:
        dict: Result with old_profile, new_profile, changed, etc.
    """
    return sync_user_role_profile(user, dry_run=dry_run)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def bulk_recalculate_role_profiles(filters: dict = None, dry_run: bool = True):
    """
    Recalculate role profiles for multiple users.

    Args:
        filters: Optional filters for User doctype
        dry_run: If True, only show what would change (default: True for safety)

    Returns:
        dict: Summary with counts and list of changes
    """
    try:
        # Default to users with verenigingen role profiles
        if not filters:
            filters = {
                "role_profile_name": [
                    "in",
                    [PROFILE_MEMBER, PROFILE_VOLUNTEER, PROFILE_TEAM_LEADER, PROFILE_BOARD_MEMBER],
                ]
            }

        users = frappe.get_all("User", filters=filters, pluck="name")

        results = {
            "total": len(users),
            "changed": 0,
            "unchanged": 0,
            "errors": 0,
            "changes": [],
            "errors_list": [],
        }

        for user in users:
            result = sync_user_role_profile(user, dry_run=dry_run)

            if result.get("success"):
                if result.get("changed"):
                    results["changed"] += 1
                    results["changes"].append(
                        {
                            "user": user,
                            "old_role": result.get("old_profile"),
                            "new_role": result.get("new_profile"),
                            "old_module": result.get("old_module_profile"),
                            "new_module": result.get("new_module_profile"),
                            "role_changed": result.get("role_changed"),
                            "module_changed": result.get("module_changed"),
                        }
                    )
                else:
                    results["unchanged"] += 1
            else:
                results["errors"] += 1
                results["errors_list"].append({"user": user, "error": result.get("error")})

        return results

    except Exception as e:
        frappe.log_error(f"Error in bulk recalculation: {str(e)}", "Role Profile Bulk Sync Error")
        return {"success": False, "error": str(e)}


def auto_sync_on_role_change(user: str):
    """
    Automatically sync role profile when user's organizational roles change.

    Call this from event handlers when:
    - Board membership changes
    - Team leadership changes
    - Volunteer status changes

    This is a fire-and-forget function that logs errors but doesn't throw.
    """
    try:
        result = sync_user_role_profile(user, dry_run=False)
        if not result.get("success"):
            frappe.logger().warning(f"Auto-sync failed for {user}: {result.get('error')}")
        return result
    except Exception as e:
        frappe.logger().error(f"Error in auto-sync for {user}: {str(e)}")


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def validate_role_profile_data_integrity():
    """
    Validate data integrity for role profile system.

    Checks for:
    - Orphaned board/team memberships (member/volunteer doesn't exist)
    - Invalid profile references (configured profiles that don't exist)
    - Users with incorrect profiles compared to calculated profiles
    - Chapters/teams with missing profile configurations

    Returns:
        dict: Comprehensive validation report
    """
    issues = {
        "orphaned_board_members": [],
        "orphaned_team_members": [],
        "invalid_chapter_profiles": [],
        "invalid_team_profiles": [],
        "profile_mismatches": [],
        "missing_profile_configs": [],
        "summary": {},
    }

    try:
        # Check 1: Orphaned board memberships
        board_members = frappe.db.get_all(
            "Chapter Board Member", filters={"is_active": 1}, fields=["name", "parent", "volunteer"]
        )

        for bm in board_members:
            if bm.volunteer:
                # Check if volunteer exists
                if not frappe.db.exists("Volunteer", bm.volunteer):
                    issues["orphaned_board_members"].append(
                        {
                            "record": bm.name,
                            "chapter": bm.parent,
                            "volunteer": bm.volunteer,
                            "issue": "Volunteer record does not exist",
                        }
                    )
                else:
                    # Check if volunteer's member exists
                    member = frappe.db.get_value("Volunteer", bm.volunteer, "member")
                    if member and not frappe.db.exists("Member", member):
                        issues["orphaned_board_members"].append(
                            {
                                "record": bm.name,
                                "chapter": bm.parent,
                                "volunteer": bm.volunteer,
                                "member": member,
                                "issue": "Member record does not exist",
                            }
                        )

        # Check 2: Orphaned team memberships
        team_members = frappe.db.get_all(
            "Team Member", filters={"status": "Active"}, fields=["name", "parent", "volunteer"]
        )

        for tm in team_members:
            if tm.volunteer:
                if not frappe.db.exists("Volunteer", tm.volunteer):
                    issues["orphaned_team_members"].append(
                        {
                            "record": tm.name,
                            "team": tm.parent,
                            "volunteer": tm.volunteer,
                            "issue": "Volunteer record does not exist",
                        }
                    )
                else:
                    member = frappe.db.get_value("Volunteer", tm.volunteer, "member")
                    if member and not frappe.db.exists("Member", member):
                        issues["orphaned_team_members"].append(
                            {
                                "record": tm.name,
                                "team": tm.parent,
                                "volunteer": tm.volunteer,
                                "member": member,
                                "issue": "Member record does not exist",
                            }
                        )

        # Check 3: Invalid chapter profile configurations
        chapters = frappe.db.get_all("Chapter", fields=["name", "default_board_role_profile"])

        for chapter in chapters:
            if chapter.default_board_role_profile:
                if not frappe.db.exists("Role Profile", chapter.default_board_role_profile):
                    issues["invalid_chapter_profiles"].append(
                        {
                            "chapter": chapter.name,
                            "profile": chapter.default_board_role_profile,
                            "issue": "Default board role profile does not exist",
                        }
                    )

            # Check role-specific profiles
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            if chapter_doc.enable_board_role_specific_profiles:
                for mapping in chapter_doc.board_role_specific_profiles or []:
                    if mapping.role_profile and not frappe.db.exists("Role Profile", mapping.role_profile):
                        issues["invalid_chapter_profiles"].append(
                            {
                                "chapter": chapter.name,
                                "role": mapping.chapter_role,
                                "profile": mapping.role_profile,
                                "issue": "Role-specific profile does not exist",
                            }
                        )

        # Check 4: Invalid team profile configurations
        teams = frappe.db.get_all("Team", fields=["name", "default_role_profile"])

        for team in teams:
            if team.default_role_profile:
                if not frappe.db.exists("Role Profile", team.default_role_profile):
                    issues["invalid_team_profiles"].append(
                        {
                            "team": team.name,
                            "profile": team.default_role_profile,
                            "issue": "Default role profile does not exist",
                        }
                    )

            # Check role-specific profiles
            team_doc = frappe.get_doc("Team", team.name)
            if team_doc.enable_role_specific_profiles:
                for mapping in team_doc.role_specific_profiles or []:
                    if mapping.role_profile and not frappe.db.exists("Role Profile", mapping.role_profile):
                        issues["invalid_team_profiles"].append(
                            {
                                "team": team.name,
                                "role": mapping.team_role,
                                "profile": mapping.role_profile,
                                "issue": "Role-specific profile does not exist",
                            }
                        )

        # Check 5: Users with incorrect profiles (sample check)
        users_to_check = frappe.db.get_all(
            "User",
            filters={
                "role_profile_name": [
                    "in",
                    [PROFILE_MEMBER, PROFILE_VOLUNTEER, PROFILE_TEAM_LEADER, PROFILE_BOARD_MEMBER],
                ]
            },
            fields=["name", "role_profile_name"],
            limit=100,  # Limit to avoid timeout
        )

        for user in users_to_check:
            calculated_profile = calculate_user_role_profile(user.name)
            if calculated_profile and calculated_profile != user.role_profile_name:
                issues["profile_mismatches"].append(
                    {
                        "user": user.name,
                        "current_profile": user.role_profile_name,
                        "calculated_profile": calculated_profile,
                        "issue": "Current profile does not match calculated profile",
                    }
                )

        # Generate summary
        issues["summary"] = {
            "total_issues": sum(
                [
                    len(issues["orphaned_board_members"]),
                    len(issues["orphaned_team_members"]),
                    len(issues["invalid_chapter_profiles"]),
                    len(issues["invalid_team_profiles"]),
                    len(issues["profile_mismatches"]),
                ]
            ),
            "orphaned_board_members": len(issues["orphaned_board_members"]),
            "orphaned_team_members": len(issues["orphaned_team_members"]),
            "invalid_chapter_profiles": len(issues["invalid_chapter_profiles"]),
            "invalid_team_profiles": len(issues["invalid_team_profiles"]),
            "profile_mismatches": len(issues["profile_mismatches"]),
            "validation_timestamp": now_datetime().isoformat(),
        }

        return {"success": True, "issues": issues}

    except Exception as e:
        frappe.log_error(
            f"Error validating role profile data integrity: {str(e)}", "Role Profile Data Integrity Error"
        )
        return {"success": False, "error": str(e)}
