# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
AccountCreationService - Single source of truth for user account creation logic

This service consolidates all account creation validation, existing user detection,
and user-member linking logic that was previously scattered across three code paths:
- AccountCreationManager._create_user_account() (individual creation)
- AccountCreationManager.queue_bulk_account_creation_for_members() (bulk creation)
- MijnroodCSVImport._process_user_account_creation() (CSV import)

The service ensures correct handling of the one-way Member→User relationship and
eliminates DRY violations through a single, well-tested implementation.

Architecture:
    Member DocType                    User DocType
    ├─ name (PK)                     ├─ name (PK)
    ├─ email                         ├─ email
    ├─ first_name                    ├─ first_name
    ├─ last_name                     ├─ last_name
    └─ user (Link) ──────────────────┘ [NO reciprocal field]

Key Design Decisions:
- Uses Member.user field to store User.name (one-way relationship)
- Never attempts to set non-existent User.custom_member field
- Queries existing user linkage via Member table, not User table
- Validates name matching for security when linking to existing users
"""

from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.model.document import Document


class AccountCreationService:
    """
    Service for user account creation with proper relationship management.

    This service is the single source of truth for:
    - Member validation for account eligibility
    - Existing user detection via correct relationship direction
    - User-member linking with security validation
    - Bulk account request orchestration
    """

    # Valid member statuses for account creation
    VALID_ACCOUNT_STATUSES = ["Active", "Pending", "Suspended"]

    # Member statuses that should never get user accounts
    INVALID_ACCOUNT_STATUSES = ["Terminated", "Banned", "Deceased", "Rejected"]

    def __init__(self):
        """Initialize the service."""
        pass

    def validate_member_for_account(self, member: Document) -> Tuple[bool, Optional[str]]:
        """
        Validate that a member is eligible for user account creation.

        Checks:
        - Member has email address
        - Member status allows account creation
        - Member doesn't already have a user account linked

        Args:
            member: Member document to validate

        Returns:
            Tuple of (is_valid, error_message)
            - (True, None) if valid
            - (False, "error description") if invalid
        """
        # Check email exists
        if not member.email:
            return False, f"Member {member.name} has no email address"

        # Check email format (basic validation)
        if "@" not in member.email or "." not in member.email:
            return False, f"Member {member.name} has invalid email format: {member.email}"

        # Check status allows account creation
        if member.status in self.INVALID_ACCOUNT_STATUSES:
            return False, f"Member {member.name} has status '{member.status}' which cannot have user accounts"

        # Check if member already has a user account linked
        if member.user:
            # Verify the linked user actually exists
            if frappe.db.exists("User", member.user):
                # User exists - check if all requested artifacts are also present
                missing_artifacts = []

                # Check if volunteer record is required and missing
                if create_employee and "Verenigingen Volunteer" in [r.get("role") for r in roles]:
                    if not frappe.db.exists("Volunteer", {"member": member.name}):
                        missing_artifacts.append("Volunteer record")

                # Check if employee record is required and missing
                if create_employee:
                    user_has_employee = frappe.db.exists("Employee", {"user_id": member.user})
                    if not user_has_employee:
                        missing_artifacts.append("Employee record")

                # Check if required roles are assigned
                if roles:
                    user_doc = frappe.get_doc("User", member.user)
                    current_roles = [r.role for r in user_doc.roles]
                    missing_roles = [r.get("role") for r in roles if r.get("role") not in current_roles]
                    if missing_roles:
                        missing_artifacts.append(f"Roles: {', '.join(missing_roles)}")

                # If artifacts are missing, allow ACR creation to complete the setup
                if missing_artifacts:
                    frappe.logger().info(
                        f"Member {member.name} has user account but missing: {', '.join(missing_artifacts)}. "
                        "Creating ACR to complete setup."
                    )
                    return True, None

                # Everything is complete - skip ACR creation
                return False, f"Member {member.name} already has complete account setup: {member.user}"
            else:
                # Stale link - log warning but allow creation
                frappe.logger().warning(
                    f"Member {member.name} has stale user link to {member.user} (user deleted). "
                    "Will allow new account creation."
                )

        return True, None

    def detect_existing_user(self, email: str) -> Optional[Dict]:
        """
        Detect if a user account already exists with the given email.

        Uses CORRECT relationship direction: Queries User table for email,
        then queries Member table to check if that user is already linked.

        DOES NOT query non-existent User.custom_member field.

        Args:
            email: Email address to check

        Returns:
            None if no user exists, or dict with:
            {
                "user_name": str,         # User.name
                "first_name": str,        # User.first_name
                "last_name": str,         # User.last_name
                "linked_member": str|None # Member.name if linked, None if not
            }
        """
        # Query User table for account with this email
        user_data = frappe.db.get_value(
            "User", {"email": email}, ["name", "first_name", "last_name"], as_dict=True
        )

        if not user_data:
            return None

        # Check if this user is already linked to ANY member
        # CORRECT: Query Member.user field, not non-existent User.custom_member
        linked_member = frappe.db.get_value("Member", {"user": user_data.name}, "name")

        return {
            "user_name": user_data.name,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "linked_member": linked_member,
        }

    def link_existing_user(
        self, member: Document, user_name: str, validate_names: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Link an existing user account to a member.

        Sets Member.user field to establish the one-way relationship.
        DOES NOT attempt to set non-existent User.custom_member field.

        Args:
            member: Member document to link
            user_name: Name of existing User document
            validate_names: If True, verify member and user names match (security)

        Returns:
            Tuple of (success, error_message)
            - (True, None) if linked successfully
            - (False, "error description") if linking failed
        """
        # Verify user exists
        user_data = frappe.db.get_value("User", user_name, ["first_name", "last_name", "email"], as_dict=True)

        if not user_data:
            return False, f"User {user_name} does not exist"

        # Security validation: Names must match
        if validate_names:
            names_match = (
                user_data.first_name == member.first_name and user_data.last_name == member.last_name
            )

            if not names_match:
                error_msg = (
                    f"Security: Cannot link user {user_name} to member {member.name}. "
                    f"Names do not match: User({user_data.first_name} {user_data.last_name}) != "
                    f"Member({member.first_name} {member.last_name})"
                )
                frappe.logger().warning(error_msg)
                return False, error_msg

        # Check if user is already linked to a different member
        existing_user_info = self.detect_existing_user(user_data.email)
        if existing_user_info and existing_user_info["linked_member"]:
            if existing_user_info["linked_member"] != member.name:
                return False, (
                    f"Security: User {user_name} is already linked to different member "
                    f"{existing_user_info['linked_member']}"
                )
            else:
                # Already linked to this member - idempotent operation
                frappe.logger().info(
                    f"User {user_name} already linked to member {member.name}, no action needed"
                )
                return True, None

        # Set Member.user field (CORRECT relationship direction)
        try:
            frappe.db.set_value("Member", member.name, "user", user_name, update_modified=False)
            frappe.db.commit()

            frappe.logger().info(
                f"Linked existing user {user_name} ({user_data.email}) to member {member.name}"
            )
            return True, None

        except Exception as e:
            frappe.db.rollback()
            error_msg = f"Failed to link user {user_name} to member {member.name}: {str(e)}"
            frappe.logger().error(error_msg)
            return False, error_msg

    def create_account_request(
        self,
        member: Document,
        roles: List[str],
        role_profile: Optional[str] = None,
        priority: str = "Normal",
        create_employee: bool = False,
        justification: Optional[str] = None,
    ) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        Create an account creation request for a member.

        This method handles the orchestration of:
        - Member validation
        - Existing user detection
        - Request creation or user linking

        Args:
            member: Member document to create account for
            roles: List of role names to assign
            role_profile: Optional role profile name
            priority: Request priority (Normal, Low, High)
            create_employee: Whether to create Employee record
            justification: Reason for account creation

        Returns:
            Tuple of (success, error_message, result_dict)
            - (True, None, {"action": "created", "request_name": "..."}) if request created
            - (True, None, {"action": "linked", "user_name": "..."}) if linked to existing user
            - (False, "error", None) if failed
        """
        # Validate member eligibility
        is_valid, error_msg = self.validate_member_for_account(member)
        if not is_valid:
            return False, error_msg, None

        # Check for existing user with this email
        existing_user_info = self.detect_existing_user(member.email)

        if existing_user_info:
            # User exists - attempt to link if not already linked
            if existing_user_info["linked_member"]:
                if existing_user_info["linked_member"] == member.name:
                    # Already linked - nothing to do
                    return (
                        True,
                        None,
                        {"action": "already_linked", "user_name": existing_user_info["user_name"]},
                    )
                else:
                    # Linked to different member - security violation
                    return (
                        False,
                        (
                            f"User with email {member.email} is already linked to different member "
                            f"{existing_user_info['linked_member']}"
                        ),
                        None,
                    )
            else:
                # User exists but not linked - attempt linking
                success, error = self.link_existing_user(
                    member, existing_user_info["user_name"], validate_names=True
                )

                if success:
                    return True, None, {"action": "linked", "user_name": existing_user_info["user_name"]}
                else:
                    # Linking failed (likely name mismatch) - need to create new request
                    frappe.logger().warning(
                        f"Could not link existing user {existing_user_info['user_name']} "
                        f"to member {member.name}: {error}. Will create new request."
                    )
                    # Fall through to request creation

        # No existing user or linking failed - create account creation request
        # Check if request already exists
        existing_request = frappe.db.exists(
            "Account Creation Request", {"source_record": member.name, "request_type": "Member"}
        )

        if existing_request:
            return False, f"Account creation request already exists: {existing_request}", None

        # Create the request
        try:
            request_doc = frappe.get_doc(
                {
                    "doctype": "Account Creation Request",
                    "source_record": member.name,
                    "request_type": "Member",
                    "email": member.email,  # Required field
                    "full_name": member.full_name,  # Required field
                    "priority": priority,
                    "justification": justification or "Account creation via AccountCreationService",
                    "requested_roles": [{"role": role} for role in roles],
                    "role_profile": role_profile,
                    "create_employee_record": (
                        1 if create_employee else 0
                    ),  # Persistent field for employee creation
                }
            )

            request_doc.insert()
            frappe.db.commit()

            return True, None, {"action": "created", "request_name": request_doc.name}

        except Exception as e:
            frappe.db.rollback()
            error_msg = f"Failed to create account request for {member.name}: {str(e)}"
            frappe.logger().error(error_msg)
            return False, error_msg, None

    def queue_bulk_requests(
        self,
        member_names: List[str],
        roles: List[str],
        role_profile: Optional[str] = None,
        batch_size: int = 50,
        priority: str = "Low",
        create_employee: bool = False,
        filter_by_status: bool = True,
    ) -> Dict:
        """
        Queue bulk account creation requests for multiple members.

        This is the consolidated implementation that replaces the three previous
        code paths with a single, tested approach.

        Args:
            member_names: List of Member document names
            roles: List of role names to assign to all members
            role_profile: Optional role profile name
            batch_size: Number of members to process per batch
            priority: Request priority (Normal, Low, High)
            create_employee: Whether to create Employee records
            filter_by_status: If True, only process Active members

        Returns:
            Dict with:
            {
                "success": bool,
                "requests_created": int,
                "users_linked": int,
                "validation_errors_count": int,
                "validation_errors": List[str],
                "request_names": List[str],
                "linked_users": List[str]
            }
        """
        frappe.logger().info(
            f"[AccountCreationService] Starting bulk requests for {len(member_names)} members, "
            f"create_employee={create_employee}, filter_by_status={filter_by_status}"
        )

        validation_errors = []
        requests_created = []
        users_linked = []
        already_has_account = []  # Track members who already have accounts
        skipped_by_status = []  # Track members skipped due to status

        for idx, member_name in enumerate(member_names, 1):
            try:
                # Load member document
                member = frappe.get_doc("Member", member_name)

                # Filter by status if requested
                if filter_by_status and member.status not in self.VALID_ACCOUNT_STATUSES:
                    skipped_by_status.append(f"{member_name} ({member.status})")
                    frappe.logger().debug(
                        f"[AccountCreationService] {idx}/{len(member_names)}: Skipped {member_name} - "
                        f"status '{member.status}' not in {self.VALID_ACCOUNT_STATUSES}"
                    )
                    continue

                # Create request or link existing user
                success, error, result = self.create_account_request(
                    member=member,
                    roles=roles,
                    role_profile=role_profile,
                    priority=priority,
                    create_employee=create_employee,
                    justification=f"Bulk account creation for {len(member_names)} members",
                )

                if success:
                    if result["action"] == "created":
                        requests_created.append(result["request_name"])
                        frappe.logger().info(
                            f"[AccountCreationService] {idx}/{len(member_names)}: Created request "
                            f"{result['request_name']} for {member_name}"
                        )
                    elif result["action"] == "linked":
                        users_linked.append(result["user_name"])
                        frappe.logger().info(
                            f"[AccountCreationService] {idx}/{len(member_names)}: Linked existing user "
                            f"{result['user_name']} to {member_name}"
                        )
                    elif result["action"] == "already_linked":
                        # Already has account - not an error, but track it
                        already_has_account.append(f"{member_name} → {result['user_name']}")
                        frappe.logger().debug(
                            f"[AccountCreationService] {idx}/{len(member_names)}: {member_name} already "
                            f"linked to {result['user_name']}, skipping"
                        )
                else:
                    validation_errors.append(f"{member_name}: {error}")
                    frappe.logger().warning(
                        f"[AccountCreationService] {idx}/{len(member_names)}: Failed for {member_name}: {error}"
                    )

            except frappe.DoesNotExistError:
                validation_errors.append(f"Member {member_name} does not exist")
                frappe.logger().error(f"[AccountCreationService] Member {member_name} does not exist")
            except Exception as e:
                validation_errors.append(f"Member {member_name}: Unexpected error - {str(e)}")
                frappe.logger().error(
                    f"[AccountCreationService] Unexpected error for {member_name}: {str(e)}", exc_info=True
                )

        # Log comprehensive summary
        frappe.logger().info(
            f"[AccountCreationService] BULK COMPLETE: "
            f"{len(requests_created)} requests created, "
            f"{len(users_linked)} users linked, "
            f"{len(already_has_account)} already had accounts, "
            f"{len(skipped_by_status)} skipped by status, "
            f"{len(validation_errors)} validation errors"
        )

        # Log details of what was skipped
        if skipped_by_status:
            frappe.logger().info(
                f"[AccountCreationService] Skipped by status: {skipped_by_status[:10]}"
                + (f" ... and {len(skipped_by_status) - 10} more" if len(skipped_by_status) > 10 else "")
            )

        if already_has_account:
            frappe.logger().info(
                f"[AccountCreationService] Already had accounts: {already_has_account[:10]}"
                + (f" ... and {len(already_has_account) - 10} more" if len(already_has_account) > 10 else "")
            )

        return {
            "success": True,  # Overall process succeeded even if some members failed
            "requests_created": len(requests_created),
            "users_linked": len(users_linked),
            "validation_errors_count": len(validation_errors),
            "validation_errors": validation_errors[:50],  # Limit to first 50
            "request_names": requests_created,
            "linked_users": users_linked,
        }


def get_account_creation_service() -> AccountCreationService:
    """
    Factory function to get AccountCreationService instance.

    This allows for future dependency injection or service configuration
    without changing calling code.

    Returns:
        AccountCreationService instance
    """
    return AccountCreationService()
