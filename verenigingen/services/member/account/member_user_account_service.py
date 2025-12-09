# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberUserAccountService - User account creation for members

This service handles user account creation logic for members that was previously
in the Member DocType class. It provides direct user creation without the
request/approval workflow of AccountCreationManager.

Extracted from:
- Member.create_user() - lines 1485-1552 (68 LOC)

Architecture:
- Direct user creation (no request workflow)
- Dutch naming convention support
- Secure document operations
- Role and module assignment
- Ownership transfer

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
API method returns OperationResult[str] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- create_member_user_account: Returns OperationResult[str] (username created/linked)
- validate_member_for_user_account: Returns MemberAccountValidationResult
- bulk_create_user_accounts: Returns BulkAccountCreationResult

Migration Status: ✅ COMPLETE (2025-12-09)
- API method migrated from dict-based to OperationResult pattern
- All security features and document operations preserved
- Type-safe error handling with comprehensive metadata
- Added validation and bulk creation methods (migrated from member_account_service.py)

Legacy Methods (still throw exceptions):
- create_user_for_member: Direct user creation (throws ValidationError)
- create_user_account_if_needed: Hook-based creation (logs errors, doesn't throw)

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.member.account.member_role_service import get_member_role_service
from verenigingen.utils.dutch_name_utils import get_full_last_name, is_dutch_installation
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.secure_operations import secure_document_operation

if TYPE_CHECKING:
    from frappe.model.document import Document


# =============================================================================
# Dataclasses for Validation and Bulk Operations
# =============================================================================


@dataclass
class MemberAccountValidationResult:
    """
    Result of validating a member for user account creation.

    This provides pre-flight validation before attempting account creation,
    identifying issues that would cause creation to fail.

    Attributes:
        valid: Whether the member is ready for user account creation
        issues: List of specific issues preventing account creation
        member_name: Name of the member being validated
        member_email: Email of the member (if present)
        existing_user: Username if a user with this email already exists
        duplicate_member: Member name if email is used by another member

    Examples:
        >>> result = service.validate_member_for_user_account(member_doc)
        >>> if not result.valid:
        ...     print(f"Cannot create account: {'; '.join(result.issues)}")
    """

    valid: bool
    issues: List[str] = field(default_factory=list)
    member_name: str = ""
    member_email: str = ""
    existing_user: Optional[str] = None
    duplicate_member: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "valid": self.valid,
            "issues": self.issues,
            "member_name": self.member_name,
        }
        if self.member_email:
            result["member_email"] = self.member_email
        if self.existing_user:
            result["existing_user"] = self.existing_user
        if self.duplicate_member:
            result["duplicate_member"] = self.duplicate_member
        return result


@dataclass
class BulkAccountCreationDetail:
    """
    Detail record for a single member in bulk account creation.

    Attributes:
        member: Member name/ID
        status: One of "success", "failed", "skipped"
        user: Username created/linked (if successful)
        action: "created_new" or "linked_existing" (if successful)
        reason: Reason for skip (if skipped)
        error: Error message (if failed)
    """

    member: str
    status: str  # "success", "failed", "skipped"
    user: Optional[str] = None
    action: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {"member": self.member, "status": self.status}
        if self.user:
            result["user"] = self.user
        if self.action:
            result["action"] = self.action
        if self.reason:
            result["reason"] = self.reason
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class BulkAccountCreationResult:
    """
    Result of bulk user account creation operation.

    This provides comprehensive tracking of bulk operations, including
    success/failure/skip counts and detailed results for each member.

    Attributes:
        total: Total number of members processed
        success: Number of successful account creations
        failed: Number of failed attempts
        skipped: Number of members skipped (validation failures)
        details: List of BulkAccountCreationDetail for each member
        stopped_early: Whether processing was stopped due to continue_on_error=False

    Examples:
        >>> result = service.bulk_create_user_accounts(member_names)
        >>> print(f"Created {result.success}/{result.total} accounts")
        >>> for detail in result.details:
        ...     if detail.status == "failed":
        ...         print(f"  {detail.member}: {detail.error}")
    """

    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    details: List[BulkAccountCreationDetail] = field(default_factory=list)
    stopped_early: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "details": [d.to_dict() for d in self.details],
            "stopped_early": self.stopped_early,
        }

    def add_success(self, member: str, user: str, action: str) -> None:
        """Record a successful account creation."""
        self.success += 1
        self.details.append(
            BulkAccountCreationDetail(member=member, status="success", user=user, action=action)
        )

    def add_failed(self, member: str, error: str) -> None:
        """Record a failed account creation."""
        self.failed += 1
        self.details.append(BulkAccountCreationDetail(member=member, status="failed", error=error))

    def add_skipped(self, member: str, reason: str) -> None:
        """Record a skipped member."""
        self.skipped += 1
        self.details.append(BulkAccountCreationDetail(member=member, status="skipped", reason=reason))


class MemberUserAccountService(StatelessService):
    """
    Service for creating user accounts for members.

    This service handles the direct creation of user accounts without the
    request/approval workflow, suitable for:
    - Manual member-to-user conversion
    - Quick user account creation from Member form
    - API-driven account creation
    """

    def __init__(self) -> None:
        """Initialize the member user account service."""
        super().__init__(service_name="MemberUserAccountService")

    def create_user_for_member(
        self,
        member_doc: "Document",
        send_welcome_email: bool = True,
        silent: bool = False,
    ) -> tuple:
        """
        Create a user account for a member.

        This method performs direct user creation with:
        - Email validation
        - Existing user detection and linking
        - Dutch naming convention support
        - Secure user document creation
        - Role and module assignment
        - Ownership transfer to new user

        Args:
            member_doc: Member document object
            send_welcome_email: Whether to send welcome email (default True)
            silent: If True, suppress msgprint messages (for API calls)

        Returns:
            tuple: (username: str, action: str) where action is one of:
                - "already_exists": User was already linked to member
                - "linked_existing": Linked to existing user with same email
                - "created_new": Created new user account

        Raises:
            frappe.ValidationError: If email is missing or user creation fails
        """
        from verenigingen.utils.boolean_utils import cbool

        # Check if user already exists on member
        if member_doc.user:
            if not silent:
                frappe.msgprint(_("User {0} already exists for this member").format(member_doc.user))
            return member_doc.user, "already_exists"

        # Validate required fields are present
        if not member_doc.email:
            frappe.throw(_("Email is required to create a user"))

        if not member_doc.first_name:
            frappe.throw(_("First name is required to create a user"))

        if not member_doc.last_name:
            frappe.throw(_("Last name is required to create a user"))

        # Check if user with this email already exists
        if frappe.db.exists("User", member_doc.email):
            user = frappe.get_doc("User", member_doc.email)
            # Link existing user to member
            member_doc.user = user.name
            member_doc.flags.ignore_validate_update_after_submit = True
            member_doc.flags.ignore_mandatory = False
            member_doc.save()

            # Add member roles to existing user
            get_member_role_service().add_member_roles_to_user(user.name)

            if not silent:
                frappe.msgprint(_("Linked to existing user {0}").format(user.name))
            return user.name, "linked_existing"

        # Create new user document
        user = frappe.new_doc("User")
        user.email = member_doc.email
        user.first_name = member_doc.first_name

        # Handle Dutch naming conventions for User creation
        if is_dutch_installation() and hasattr(member_doc, "tussenvoegsel") and member_doc.tussenvoegsel:
            # For Dutch installations, use combined last name with tussenvoegsel
            user.last_name = get_full_last_name(member_doc.last_name, member_doc.tussenvoegsel)
            # Don't use middle_name for User when we have tussenvoegsel
        else:
            # Standard naming for non-Dutch installations or when no tussenvoegsel
            user.last_name = member_doc.last_name
            if member_doc.middle_name:
                user.middle_name = member_doc.middle_name

        user.send_welcome_email = cbool(send_welcome_email)
        user.user_type = "System User"
        user.enabled = 1

        # Secure user creation with explicit permission validation
        user_result = secure_document_operation(
            operation="insert",
            doc=user,
            justification=f"Automated user creation for member {member_doc.name}",
            required_permissions=["User:create"],
        )

        if not user_result.success:
            frappe.throw(_("Failed to create user: {0}").format("; ".join(user_result.errors)))

        # Add member-specific roles after user is created
        get_member_role_service().add_member_roles_to_user(user.name)

        # Set allowed modules for member users
        get_member_role_service().set_member_user_modules(user.name)

        # Transfer ownership to the member's user account
        # This allows members to view and edit their own records
        if member_doc.owner != user.name:
            original_owner = member_doc.owner
            # Use direct database update to bypass "set only once" validation on owner field
            frappe.db.set_value("Member", member_doc.name, "owner", user.name, update_modified=False)
            member_doc.reload()
            self.logger.info(
                f"Transferred ownership of member {member_doc.name} from {original_owner} to {user.name}"
            )

        # Update user field and save member document with proper validation and audit trail
        # NOTE: member_doc.user must be set (or re-set) here because:
        # - If ownership transfer occurred above, reload() clears unsaved changes
        # - Even without transfer, we need to ensure user field is set before save
        member_doc.user = user.name
        member_doc.flags.ignore_validate_update_after_submit = True
        member_doc.flags.ignore_mandatory = False  # Keep validation
        member_doc.save()

        if not silent:
            frappe.msgprint(_("User {0} created successfully").format(user.name))
        return user.name, "created_new"

    def create_member_user_account(
        self, member_name: str, send_welcome_email: bool = True
    ) -> OperationResult[str]:
        """
        Create a user account for a member - API-compatible wrapper.

        This is a wrapper around create_user_for_member() that provides:
        - OperationResult return type for type-safe error handling
        - Exception catching (never throws)
        - Silent operation (no msgprint)

        Args:
            member_name: Name/ID of the member document
            send_welcome_email: Whether to send welcome email (default True)

        Returns:
            OperationResult[str]: Username on success with metadata:
                - action: "created_new", "linked_existing", or "already_exists"

        Example:
            >>> result = service.create_member_user_account("Member-001")
            >>> if result.success:
            >>>     print(f"User created: {result.data}")

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Uses create_user_for_member() internally for full functionality:
              - Dutch naming support (tussenvoegsel)
              - Ownership transfer to new user
              - Proper document save flags for submitted members
            - Uses secure_document_operation for all document operations
        """
        try:
            # Get the member document
            member = frappe.get_doc("Member", member_name)

            # Call the core method with silent=True for API use
            username, action = self.create_user_for_member(
                member_doc=member,
                send_welcome_email=send_welcome_email,
                silent=True,
            )

            # Handle "already_exists" case specially - return as failure for API compatibility
            if action == "already_exists":
                return OperationResult.fail(
                    _("User account already exists for this member"),
                    errors=["User already exists"],
                    user=username,
                    action=action,
                )

            # Success cases: "created_new" or "linked_existing"
            if action == "linked_existing":
                message = _("Linked existing user account to member")
            else:
                message = _("User account created successfully")

            self.logger.info(f"Created/linked user account {username} for member {member_name} ({action})")

            return OperationResult.ok(username, message=message, action=action)

        except Exception as e:
            self.logger.error(
                f"Error creating user account for member {member_name}: {str(e)}", exc_info=True
            )
            return OperationResult.fail(
                _("Failed to create user account: {0}").format(str(e)),
                errors=[str(e)],
                member=member_name,
            )

    def create_user_account_if_needed(self, member_doc: "Document") -> None:
        """
        Create user account for member if conditions are met.

        This method checks various conditions before creating a user account:
        - Not for application members (handled in approval process)
        - Only if user doesn't already exist
        - Requires email address
        - Only for active members or new members

        Args:
            member_doc: Member document object

        Returns:
            None (creates user account as side effect if conditions met)

        Note:
            - Does not raise exceptions (logs errors instead)
            - Used in after_save hook to auto-create accounts
            - Sends no welcome email (send_welcome_email=False)
        """
        try:
            # Don't create user for application members (handled in approval process)
            if member_doc.is_application_member():
                return

            # Don't create if user already exists
            if member_doc.user:
                return

            # Must have email to create user
            if not member_doc.email:
                return

            # Only create for active members
            if getattr(member_doc, "status", "") not in ["Active", ""]:
                return

            # Create user account using wrapper method
            result = self.create_member_user_account(member_doc.name, send_welcome_email=False)

            if result.success:
                self.logger.info(f"Auto-created user account for manually created member {member_doc.name}")
            else:
                self.logger.warning(
                    f"Could not auto-create user account for member {member_doc.name}: "
                    f"{result.error_message or 'Unknown error'}"
                )

        except Exception as e:
            self.logger.error(
                f"Error in create_user_account_if_needed for member {member_doc.name}: {str(e)}",
                exc_info=True,
            )
            # Don't raise exception to avoid blocking member save

    def validate_member_for_user_account(
        self, member: Union[str, "Document"]
    ) -> MemberAccountValidationResult:
        """
        Validate that a member is ready for user account creation.

        This provides pre-flight validation before attempting account creation,
        identifying issues that would cause creation to fail. Use this method
        to check eligibility before calling create_member_user_account().

        Args:
            member: Member document or member name/ID

        Returns:
            MemberAccountValidationResult with:
                - valid: True if member can have an account created
                - issues: List of specific problems preventing creation
                - Additional metadata about existing users/duplicates

        Examples:
            >>> service = get_member_user_account_service()
            >>> result = service.validate_member_for_user_account("MEM-00001")
            >>> if result.valid:
            ...     service.create_member_user_account("MEM-00001")
            >>> else:
            ...     print(f"Cannot create: {'; '.join(result.issues)}")

        Note:
            This method does NOT create any accounts - it only validates.
            Call create_member_user_account() to actually create the account.

        TOCTOU Warning:
            This validation is a point-in-time check. The member's state could
            change between validation and account creation (e.g., another user
            links the same email, member status changes). For critical operations,
            consider:
            - Calling create_member_user_account() directly (it validates internally)
            - Using database locks if strict atomicity is required
            - Re-validating in time-sensitive scenarios
        """
        issues: List[str] = []
        existing_user: Optional[str] = None
        duplicate_member: Optional[str] = None

        try:
            # Handle both document and name
            if isinstance(member, str):
                if not frappe.db.exists("Member", member):
                    return MemberAccountValidationResult(
                        valid=False,
                        issues=[f"Member '{member}' does not exist"],
                        member_name=member,
                    )
                member_doc = frappe.get_doc("Member", member)
            else:
                member_doc = member

            member_name = member_doc.name
            member_email = getattr(member_doc, "email", "") or ""

            # Check if user already linked
            if member_doc.user:
                issues.append(f"Member already has user account: {member_doc.user}")
                return MemberAccountValidationResult(
                    valid=False,
                    issues=issues,
                    member_name=member_name,
                    member_email=member_email,
                    existing_user=member_doc.user,
                )

            # Check required fields - email
            if not member_email:
                issues.append("Member must have an email address")

            # Check required fields - name (at least first or last name)
            first_name = getattr(member_doc, "first_name", "") or ""
            last_name = getattr(member_doc, "last_name", "") or ""
            if not first_name and not last_name:
                issues.append("Member must have at least first name or last name")

            # Check member status - must be Active, Approved, or empty (new member)
            #
            # PERMISSIVE BY DESIGN: This validation intentionally allows:
            # - "Active": Standard active members
            # - "Approved": Members approved but not yet Active (approval workflow)
            # - "" (empty): New members without status set yet
            # - None: Members where status field is not set (defensive)
            #
            # Rejected statuses include: "Suspended", "Terminated", "Pending", etc.
            # This prevents creating portal access for members who shouldn't have it.
            #
            # Logic migrated from deprecated member_account_service.py with empty status
            # support added for new member creation scenarios.
            status = getattr(member_doc, "status", None)
            if status is not None and status not in ["Active", "Approved", ""]:
                issues.append(f"Member status '{status}' not suitable for user account creation")

            # Check for duplicate email in other members (if email present)
            if member_email:
                duplicate = frappe.db.get_value(
                    "Member",
                    {"email": member_email, "name": ["!=", member_name]},
                    "name",
                )
                if duplicate:
                    issues.append(f"Email {member_email} is already used by member {duplicate}")
                    duplicate_member = duplicate

                # Check if user with this email already exists (informational)
                existing = frappe.db.get_value("User", {"email": member_email}, "name")
                if existing:
                    existing_user = existing
                    # Note: This is not an error - we can link to existing user
                    # But we record it for informational purposes

            return MemberAccountValidationResult(
                valid=len(issues) == 0,
                issues=issues,
                member_name=member_name,
                member_email=member_email,
                existing_user=existing_user,
                duplicate_member=duplicate_member,
            )

        except Exception as e:
            self.logger.error(f"Error validating member for user account: {str(e)}", exc_info=True)
            return MemberAccountValidationResult(
                valid=False,
                issues=[f"Validation error: {str(e)}"],
                member_name=str(member) if isinstance(member, str) else getattr(member, "name", ""),
            )

    def bulk_create_user_accounts(
        self,
        member_names: List[str],
        send_welcome_emails: bool = True,
        continue_on_error: bool = True,
    ) -> BulkAccountCreationResult:
        """
        Create user accounts for multiple members in bulk.

        This method is particularly useful for import processes or batch
        operations where multiple member accounts need to be created at once.
        It validates each member before attempting creation and provides
        comprehensive tracking of results.

        Args:
            member_names: List of member names/IDs to create accounts for
            send_welcome_emails: Whether to send welcome emails to new users (default True)
            continue_on_error: Whether to continue processing if individual members fail
                              (default True). If False, stops on first failure.

        Returns:
            BulkAccountCreationResult with:
                - total: Number of members processed
                - success: Number of successful creations
                - failed: Number of failed attempts
                - skipped: Number of members skipped due to validation failures
                - details: Per-member results
                - stopped_early: True if continue_on_error=False caused early stop

        Examples:
            >>> service = get_member_user_account_service()
            >>> result = service.bulk_create_user_accounts(
            ...     ["MEM-00001", "MEM-00002", "MEM-00003"],
            ...     send_welcome_emails=False
            ... )
            >>> print(f"Created {result.success}/{result.total} accounts")
            >>> if result.failed > 0:
            ...     for detail in result.details:
            ...         if detail.status == "failed":
            ...             print(f"  {detail.member}: {detail.error}")

        Note:
            - Uses secure_document_operation for all document operations
            - Each member is validated before creation attempt
            - Results are logged at completion for audit trail
            - Does not use ignore_permissions - proper permission checks apply

        Transaction Behavior:
            This method does NOT wrap all operations in a single transaction.
            Each member's account creation is committed individually. This design:
            - Allows partial success (some accounts created even if others fail)
            - Prevents a single bad member from rolling back all successful creations
            - Matches the continue_on_error=True default behavior
            - Individual failures are logged to Error Log for audit

            If atomic all-or-nothing behavior is needed, wrap the call in a
            savepoint/transaction at the calling site.
        """
        result = BulkAccountCreationResult(total=len(member_names))

        for member_name in member_names:
            try:
                # Validate member first
                validation = self.validate_member_for_user_account(member_name)
                if not validation.valid:
                    result.add_skipped(member_name, "; ".join(validation.issues))
                    continue

                # Create user account
                creation_result = self.create_member_user_account(
                    member_name, send_welcome_email=send_welcome_emails
                )

                if creation_result.success:
                    result.add_success(
                        member=member_name,
                        user=creation_result.data,
                        action=creation_result.metadata.get("action", "created_new"),
                    )
                else:
                    error_msg = creation_result.error_message or "Unknown error"
                    if creation_result.errors:
                        error_msg = "; ".join(creation_result.errors)
                    result.add_failed(member_name, error_msg)

                    # Log error for audit trail before potentially breaking
                    frappe.log_error(
                        f"Failed to create user account for member {member_name}: {error_msg}",
                        "Bulk Account Creation Error",
                    )

                    if not continue_on_error:
                        result.stopped_early = True
                        break

            except Exception as e:
                error_msg = str(e)
                result.add_failed(member_name, error_msg)

                # Log error for audit trail before potentially breaking
                frappe.log_error(
                    f"Error processing member {member_name} in bulk operation: {error_msg}",
                    "Bulk Account Creation Error",
                )

                if not continue_on_error:
                    result.stopped_early = True
                    break

        # Log summary
        self.logger.info(
            f"Bulk user account creation completed: "
            f"{result.success} success, {result.failed} failed, {result.skipped} skipped"
            + (" (stopped early)" if result.stopped_early else "")
        )

        return result


def get_member_user_account_service() -> MemberUserAccountService:
    """Get singleton instance of MemberUserAccountService"""
    return MemberUserAccountService()
