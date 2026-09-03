"""
Volunteer DocType Implementation

This module implements the Volunteer DocType for the Verenigingen association
management system. It manages volunteer registration, assignments, tracking,
and coordination with comprehensive validation and business logic.

Key Features:
    - Volunteer registration and profile management
    - Member integration with shared contact information
    - Assignment tracking and aggregation
    - Age validation and compliance checking
    - Dutch name formatting for localization
    - Address and contact management integration

Business Logic:
    - Volunteers must be at least 16 years old
    - Integration with Member records for shared information
    - Automatic contact information inheritance from linked members
    - Assignment aggregation from multiple sources
    - Date validation and consistency checking

Architecture:
    - Document-based with comprehensive validation hooks
    - Integration with Member DocType for shared data
    - Address and contact system integration
    - Caching for performance optimization
    - Event-driven assignment tracking

Validation Rules:
    - Required field validation with sensible defaults
    - Member link validation and existence checking
    - Age requirement validation (minimum 16 years)
    - Date consistency and logical validation
    - Contact information validation through inheritance

Integration Points:
    - Member DocType for personal information
    - Address and Contact systems for location data
    - Assignment tracking systems
    - Chapter management for volunteer coordination
    - Expense management for volunteer reimbursements

Security Model:
    - Standard document permissions
    - Member-based access controls
    - Assignment visibility controls
    - Personal information protection

Performance Considerations:
    - Cached aggregated assignments
    - Efficient member data lookup
    - Optimized address and contact loading
    - Query optimization for assignment aggregation

Author: Verenigingen Development Team
License: MIT
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.contacts.address_and_contact import load_address_and_contact
from frappe.model.document import Document
from frappe.utils import getdate, today

from verenigingen.services.member.utils.member_age_service import calculate_member_age
from verenigingen.services.volunteer.status_derivation_service import (
    get_volunteer_status_derivation_service,
)
from verenigingen.utils.dutch_name_utils import format_dutch_full_name
from verenigingen.utils.member_utils import get_volunteer_for_member
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.select_options import coerce_select_option
from verenigingen.utils.validation_utilities import AgeValidator, DocumentExistenceValidator


def safe_log_error(message: str, title: Optional[str] = None) -> None:
    """Helper to log errors with length protection"""
    # Truncate message to prevent log title validation errors
    safe_message = message[:100] + "..." if len(message) > 100 else message
    frappe.log_error(safe_message, title)


class Volunteer(Document):
    def onload(self) -> None:
        """Load address and contacts in `__onload`"""
        # If this volunteer is linked to a member, load member's address and contact info
        if self.member:
            # Load address and contact from the linked member instead of volunteer
            member_doc = frappe.get_doc("Member", self.member)
            load_address_and_contact(member_doc)
            # Copy the loaded address and contact info to volunteer
            if hasattr(member_doc, "__onload"):
                if not hasattr(self, "__onload"):
                    self.set("__onload", frappe._dict())
                self.get("__onload").update(member_doc.get("__onload"))
        else:
            # Fallback to volunteer's own address/contact if no member is linked
            load_address_and_contact(self)

        # Load aggregated assignments
        self.load_aggregated_assignments()

    def load_aggregated_assignments(self) -> None:
        """Load aggregated assignments from all sources"""
        self.get("__onload").aggregated_assignments = self.get_aggregated_assignments()

    def validate(self) -> None:
        """Validate volunteer data"""
        self.validate_required_fields()
        self.validate_member_link()
        self.validate_unique_member_link()
        self.validate_volunteer_age()
        self.validate_dates()
        self.validate_retired_has_no_current_assignment()

    def validate_required_fields(self):
        """Check if required fields are filled"""
        if not self.start_date:
            self.start_date = today()

    def validate_member_link(self):
        """Validate that member link is valid"""
        if self.member and not DocumentExistenceValidator.validate_document_exists(
            "Member", self.member, throw_on_error=False
        ):
            frappe.throw(_("Member {0} does not exist").format(self.member), frappe.DoesNotExistError)

    def validate_unique_member_link(self):
        """Refuse a second Volunteer for a member who already has one.

        This is for the MESSAGE, not the enforcement: two concurrent inserts both
        pass validate() and only the unique index on `member` stops the second. It
        exists because the four creation paths that already guard this
        (create_volunteer_from_member, the bulk creation service,
        api/volunteer_application.py, mijnrood's sync service) all check-then-insert,
        and a swallowed error in the check silently produces the duplicate --
        utils/member_utils.py:361 documents that as an observed outcome.

        Duplicates are not merely redundant data. Half the codebase resolves this
        link with a single-row lookup (get_volunteer_for_member) and half iterates
        (permissions.py:1500, :1533, :1578), so a second record makes lookups --
        including authorization ones -- depend on which row wins. See #267.

        self.name is already set here: insert() calls set_new_name (document.py:479)
        before _validate (:485), so excluding the document being saved works on
        insert as well as on update.
        """
        if not self.member:
            return

        filters = {"member": self.member}
        if self.name:
            filters["name"] = ("!=", self.name)

        existing = frappe.db.get_value("Volunteer", filters, "name")
        if existing:
            frappe.throw(
                _("Member {0} already has a Volunteer record: {1}").format(self.member, existing),
                frappe.UniqueValidationError,
            )

    def validate_volunteer_age(self):
        """Validate volunteer age requirements"""
        if not self.member:
            return  # Skip if no member linked

        try:
            # Get member's age
            member = frappe.get_doc("Member", self.member)
            if not member.birth_date:
                return  # Skip if no birth date

            # Compute from birth_date; do NOT read the stored `Member.age`: that
            # column is NOT NULL DEFAULT 0 (an uncomputed row reads 0, below every
            # minimum) and refreshes only on save, so it lags up to a year. Harmless
            # while the rejection below was swallowed; now that it blocks the save a
            # stale age would falsely refuse. Measurements #658; class #657.
            age = calculate_member_age(member.birth_date)
            if age is None:
                # Unparseable birth date; already logged by the service, and None
                # would raise TypeError against the minimum below.
                return

            # Get minimum volunteer age from Verenigingen Settings, via the same
            # gate AgeValidator uses. Deliberately no hardcoded fallback: a
            # missing/zero setting is a configuration error, not something to
            # silently paper over. A prior `settings.get(...) or 16` disagreed
            # with that policy -- this insert used to succeed on the exact input
            # the desk path refuses (#673).
            min_volunteer_age = AgeValidator._get_configurable_min_age("volunteer")

            if age < min_volunteer_age:
                frappe.throw(
                    _("Volunteers must be at least {0} years old. Member age: {1}").format(
                        min_volunteer_age, age
                    ),
                    frappe.ValidationError,
                )

        except frappe.ValidationError:
            # The rejection above IS a frappe.ValidationError and the broad handler
            # below caught it, so the Volunteer was created anyway -- the rule was
            # dead (#658). Same fix as 36bb501b9. Also propagates get_doc()'s
            # DoesNotExistError, which validate_member_link() already throws for.
            # _get_configurable_min_age's config-error throw is also a
            # frappe.ValidationError and must propagate the same way (#673).
            raise
        except Exception as e:
            frappe.log_error(
                title="Volunteer Age Validation Error",
                message=f"Error validating volunteer age for {self.name}: {str(e)}",
            )

    def validate_dates(self):
        """Validate date fields in child tables"""
        for assignment in self.assignment_history:
            if assignment.end_date and assignment.start_date:
                start_date = getdate(assignment.start_date)
                end_date = getdate(assignment.end_date)
                if start_date > end_date:
                    frappe.throw(
                        _("Assignment start date cannot be after end date for {0}").format(assignment.role)
                    )

    def before_save(self) -> None:
        """Actions before saving volunteer record"""
        # Track status before update for auto-activation check in on_update
        self._old_status = self.get_db_value("status") if not self.is_new() else None

        # Update volunteer status based on assignments
        self.update_status()

    def on_update(self) -> None:
        """Actions after volunteer record is saved and committed"""
        # Auto-queue activation if transitioning from New to Active with assignments
        # but without an employee record yet. Done in on_update to ensure
        # the save is committed before background job processes.
        old_status = getattr(self, "_old_status", None)
        if old_status is not None:
            self._check_auto_activation(old_status)

    def after_insert(self):
        """Actions after inserting new volunteer record"""
        # Skip automatic account creation during bulk operations (CSV imports, etc.).
        # Callers may set the flag either globally (frappe.flags) when wrapping a
        # whole import, or per-document (self.flags) when creating a single
        # volunteer in a bulk context (e.g. VIP import's _create_volunteer). Honor
        # both: queue_secure_account_creation commits the transaction, which would
        # otherwise bust any open savepoint used for atomic row processing.
        if getattr(frappe.flags, "bulk_member_operations", False) or self.flags.get(
            "bulk_member_operations", False
        ):
            frappe.logger().info(
                f"Skipping automatic account creation for volunteer {self.name} due to bulk operations flag"
            )
            return

        # Skip automatic account creation during tests if flag is set (global or per-doc)
        if frappe.flags.get("skip_volunteer_account_creation", False) or self.flags.get(
            "skip_volunteer_account_creation", False
        ):
            frappe.logger().info(
                f"Skipping automatic account creation for volunteer {self.name} due to test flag"
            )
            return

        # Check if the linked member already has a user account
        existing_user = None
        if self.member:
            existing_user = frappe.db.get_value("Member", self.member, "user")
            if existing_user:
                frappe.logger().info(
                    f"Volunteer {self.name} linked to member {self.member} which already has user account {existing_user}"
                )
                # Link the volunteer to the existing user account if not already linked
                if not self.user:
                    frappe.db.set_value("Volunteer", self.name, "user", existing_user)
                    frappe.logger().info(f"Linked volunteer {self.name} to existing user {existing_user}")
                return  # Skip account creation since user already exists

        # Queue secure account creation only if no existing user account
        if self.email:
            self.queue_secure_account_creation()
        else:
            frappe.logger().warning(
                f"No email provided for volunteer {self.name} - skipping account creation"
            )

    def validate_retired_has_no_current_assignment(self):
        """Refuse a Retired status that contradicts a held role (#705)."""
        get_volunteer_status_derivation_service().validate_retired_has_no_current_assignment(self)

    def update_status(self):
        """Derive status from assignments on an ordinary save (#705)."""
        get_volunteer_status_derivation_service().update_status(self)

    def apply_assignment_derivation(self):
        """Full derivation, for use right after an assignment row changed (#705)."""
        get_volunteer_status_derivation_service().apply_assignment_derivation(self)

    def _has_current_assignment(self):
        """Does this volunteer hold a role right now? (Active, Paused or On Hold.)"""
        return get_volunteer_status_derivation_service().has_current_assignment(self)

    def _has_any_assignment(self):
        """Does this volunteer have any assignment at all, current or closed?"""
        return get_volunteer_status_derivation_service().has_any_assignment(self)

    def _check_auto_activation(self, old_status):
        """
        Auto-queue volunteer activation when assignments are added.

        If a volunteer is transitioning from "New" status to an active status
        (due to assignments being added) but doesn't have an employee record yet,
        automatically queue an Account Creation Request to complete activation.

        This ensures volunteers who join teams or chapter boards are fully activated
        for expense claim functionality without requiring manual intervention.

        Auto-activation uses base "Verenigingen Volunteer" role. Team-specific roles
        are assigned separately via team/board join workflows.
        """
        # Only process if status changed from "New" to something else
        if old_status != "New" or self.status == "New":
            return

        # Skip if already has employee record (already fully activated)
        if self.employee_id:
            return

        # Skip if no member linked (can't create ACR without member)
        if not self.member:
            frappe.logger().warning(
                f"Volunteer {self.name} activated by assignment but has no linked member - "
                "cannot auto-queue activation"
            )
            return

        # Skip during bulk operations. Honor BOTH the global flag and the per-doc
        # flag (VIP import sets it per-document), so the on_update path doesn't
        # enqueue account creation — which would COMMIT and destroy open savepoints.
        if getattr(frappe.flags, "bulk_member_operations", False) or self.flags.get(
            "bulk_member_operations", False
        ):
            return

        # Check if ACR already exists for this member (prevent duplicates)
        existing_acr = frappe.db.exists(
            "Account Creation Request",
            {"source_record": self.member, "status": ["not in", ["Completed", "Cancelled", "Failed"]]},
        )
        if existing_acr:
            frappe.logger().info(
                f"ACR {existing_acr} already exists for member {self.member} - skipping auto-activation"
            )
            return

        try:
            from verenigingen.utils.account_creation_manager import queue_account_creation_for_member

            # Queue activation with volunteer role - role_profile inference will set
            # "Verenigingen Volunteer" which triggers Employee record creation.
            result = queue_account_creation_for_member(
                member_name=self.member,
                roles=["Verenigingen Volunteer"],  # Base volunteer role
                role_profile=None,  # Inferred from roles → "Verenigingen Volunteer"
            )

            # Handle both OperationResult (has .success) and dict (from decorator serialization)
            is_success = (
                result.success
                if hasattr(result, "success")
                else result.get("success", False)
                if isinstance(result, dict)
                else False
            )

            if result and is_success:
                # Get request_name from either OperationResult.data or dict["data"]
                data = result.data if hasattr(result, "data") else result.get("data", {})
                request_name = data.get("request_name", "unknown") if data else "unknown"
                frappe.logger().info(
                    f"Auto-queued activation for volunteer {self.name} via member {self.member}: {request_name}"
                )
            else:
                # Get error message from either OperationResult.message or dict["message"]
                error_msg = (
                    result.message
                    if hasattr(result, "message")
                    else (
                        result.get("message", "No result returned")
                        if isinstance(result, dict)
                        else "No result returned"
                    )
                )
                frappe.logger().warning(
                    f"Failed to auto-queue activation for volunteer {self.name}: {error_msg}"
                )

        except frappe.PermissionError as e:
            # Re-raise permission errors - indicates security misconfiguration
            frappe.log_error(
                title="Volunteer Auto-Activation Permission Error",
                message=f"Permission denied when auto-activating volunteer {self.name}: {str(e)}",
            )
            raise

        except frappe.ValidationError as e:
            # Re-raise validation errors - data integrity issue
            frappe.log_error(
                title="Volunteer Auto-Activation Validation Error",
                message=f"Validation failed when auto-activating volunteer {self.name}: {str(e)}",
            )
            raise

        except Exception as e:
            # Log unexpected errors but don't fail the save
            frappe.log_error(
                title="Volunteer Auto-Activation Error",
                message=f"Unexpected error auto-activating volunteer {self.name}: {str(e)}",
            )

    def on_trash(self):
        """Clean up child table records before deletion to prevent orphaned data"""
        # Clean up volunteer assignment history child table
        # SECURITY: Whitelist of valid child tables to prevent SQL injection
        VALID_CHILD_TABLES = {
            "tabVolunteer Assignment",
        }

        for table_name in VALID_CHILD_TABLES:
            try:
                # Verify table exists before attempting deletion
                if not frappe.db.table_exists(table_name):
                    continue

                frappe.db.sql(
                    f"""
                    DELETE FROM `{table_name}`
                    WHERE parent = %s
                    """,
                    self.name,
                )
                frappe.logger().info(f"Cleaned up {table_name} records for {self.name}")
            except Exception as e:
                frappe.logger().debug(f"Could not clean up {table_name}: {str(e)}")

    def get_contact_link_doctype(self):
        """Override to link contacts to member if available"""
        if self.member:
            return "Member"
        return "Volunteer"

    def get_contact_link_name(self):
        """Override to link contacts to member if available"""
        if self.member:
            return self.member
        return self.name

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.UTILITY)
    def get_aggregated_assignments(self) -> List[Dict[str, Any]]:
        """Get aggregated assignments from all sources with optimized single query

        Delegates to VolunteerAssignmentService for business logic.

        Returns:
            List[Dict]: Aggregated assignments from all sources
        """
        from verenigingen.services.volunteer.assignment_service import VolunteerAssignmentService

        service = VolunteerAssignmentService(self.name)
        return service.get_aggregated_assignments()

    # Dead code removed (2025-10-19): Phase 3 refactoring - Assignment service extraction
    # Removed assignment aggregation methods (~245 lines) - now in VolunteerAssignmentService:
    # - get_aggregated_assignments_optimized() - moved to service
    # - get_aggregated_assignments_fallback() - moved to service
    # - get_volunteer_history_optimized() - moved to service (see below)
    # - get_volunteer_history_fallback() - moved to service (see below)
    # - has_active_assignments_optimized() - moved to service (see below)
    # The service provides centralized assignment aggregation logic using optimized
    # UNION queries to prevent N+1 query problems across Board, Team, and Activity sources.

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def add_activity(
        self,
        activity_type,
        role,
        description=None,
        start_date=None,
        end_date=None,
        reference_doctype=None,
        reference_name: str | None = None,
        estimated_hours=None,
        notes=None,
    ):
        """Add a new volunteer activity

        Delegates to VolunteerActivityService for business logic.

        Returns:
            str: Name of created Volunteer Activity record
        """
        from verenigingen.services.volunteer.activity_service import VolunteerActivityService

        service = VolunteerActivityService(self.name)
        return service.add_activity(
            activity_type=activity_type,
            role=role,
            description=description,
            start_date=start_date,
            end_date=end_date,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            estimated_hours=estimated_hours,
            notes=notes,
        )

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.MEMBER_DATA)
    def end_activity(self, activity_name: str, end_date=None, notes=None):
        """End a volunteer activity

        Delegates to VolunteerActivityService for business logic.

        Returns:
            bool: True if successful
        """
        from verenigingen.services.volunteer.activity_service import VolunteerActivityService

        service = VolunteerActivityService(self.name)
        service.end_activity(
            activity_name=activity_name,
            end_date=end_date,
            notes=notes,
        )
        return True

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.REPORTING)
    def get_volunteer_history(self) -> List[Dict[str, Any]]:
        """Get volunteer history in chronological order with optimized single query

        Delegates to VolunteerAssignmentService for business logic.

        Returns:
            List[Dict]: Complete volunteer history from all sources
        """
        from verenigingen.services.volunteer.assignment_service import VolunteerAssignmentService

        service = VolunteerAssignmentService(self.name)
        return service.get_volunteer_history()

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.UTILITY)
    def get_skills_by_category(self):
        """Get volunteer skills grouped by category"""
        skills_by_category = {}

        for skill in self.skills_and_qualifications:
            category = skill.skill_category
            if category not in skills_by_category:
                skills_by_category[category] = []

            skills_by_category[category].append(
                {
                    "skill": skill.volunteer_skill,
                    "level": skill.proficiency_level,
                    "experience": skill.experience_years,
                }
            )

        return skills_by_category

    @frappe.whitelist()
    @standard_api(operation_type=OperationType.REPORTING)
    def calculate_total_hours(self):
        """Calculate total volunteer hours from all activities and assignments"""
        total_hours = 0

        # Get hours from volunteer activities
        activities = frappe.get_all(
            "Volunteer Activity", filters={"volunteer": self.name}, fields=["actual_hours", "estimated_hours"]
        )

        for activity in activities:
            # Use actual hours if available, otherwise use estimated hours
            hours = activity.actual_hours or activity.estimated_hours or 0
            total_hours += hours

        # Get hours from assignment history (child table)
        for assignment in self.assignment_history:
            if assignment.actual_hours:
                total_hours += assignment.actual_hours

        return total_hours

    # Removed create_minimal_employee method - now handled by secure AccountCreationManager

    def get_expense_approver_from_assignments(self):
        """Get appropriate expense approver based on volunteer's assignments

        Delegates to VolunteerExpenseApproverService for business logic.

        Returns:
            str: User email of the expense approver
        """
        from verenigingen.services.volunteer.expense_approver_service import VolunteerExpenseApproverService

        service = VolunteerExpenseApproverService(self.name)
        return service.get_expense_approver()

    def get_board_financial_approver(self, chapter_name, exclude_volunteer=None):
        """Get financial approver from chapter board (treasurer, financial officer, etc.)

        Delegates to VolunteerExpenseApproverService for business logic.

        Args:
            chapter_name: Chapter to search for approver
            exclude_volunteer: Volunteer to exclude (for self-approval prevention)

        Returns:
            Optional[str]: User email or None
        """
        from verenigingen.services.volunteer.expense_approver_service import VolunteerExpenseApproverService

        service = VolunteerExpenseApproverService(self.name)
        return service.get_board_financial_approver(chapter_name, exclude_volunteer)

    def _ensure_user_has_expense_approver_role(self, user_email):
        """Ensure user has expense approver role

        Delegates to VolunteerExpenseApproverService for business logic.

        Args:
            user_email: User to assign role to
        """
        from verenigingen.services.volunteer.expense_approver_service import VolunteerExpenseApproverService

        service = VolunteerExpenseApproverService(self.name)
        service.ensure_user_has_expense_approver_role(user_email)

    # Removed assign_employee_role method - now handled by secure AccountCreationManager

    def queue_secure_account_creation(self):
        """Queue secure account creation through the AccountCreationManager"""
        try:
            # Import the account creation manager
            from verenigingen.utils.account_creation_manager import queue_account_creation_for_volunteer

            frappe.logger().info(f"Queueing secure account creation for volunteer {self.name}")

            # Queue account creation with proper security validation
            # Returns OperationResult or dict (if decorated function serializes it)
            result = queue_account_creation_for_volunteer(volunteer_name=self.name, priority="Normal")

            # Handle both OperationResult (has .success) and dict (from decorator serialization)
            is_success = (
                result.success
                if hasattr(result, "success")
                else result.get("success", False)
                if isinstance(result, dict)
                else False
            )

            if not is_success:
                error_msg = (
                    result.error_message
                    if hasattr(result, "error_message")
                    else (
                        result.get("message", "Unknown error")
                        if isinstance(result, dict)
                        else "Unknown error"
                    )
                )
                frappe.logger().warning(
                    f"Account creation queueing returned failure for volunteer {self.name}: {error_msg}"
                )
                return

            # Access data from either OperationResult.data or dict["data"]
            data = result.data if hasattr(result, "data") else result.get("data", {})
            request_name = data.get("request_name") if data else None
            frappe.logger().info(f"Account creation queued successfully: {request_name}")

            # Optionally notify the user about the process
            if frappe.session.user != "Administrator" and request_name:
                frappe.publish_realtime(
                    "volunteer_account_creation_queued",
                    {
                        "volunteer_name": self.name,
                        "request_name": request_name,
                        "message": "Account creation has been queued and will be processed shortly",
                    },
                    user=frappe.session.user,
                )

        except Exception as e:
            # Don't fail volunteer creation if account creation queueing fails
            frappe.logger().error(f"Failed to queue account creation for volunteer {self.name}: {str(e)}")
            safe_log_error(
                f"Account creation queueing failed for volunteer {self.name}: {str(e)}",
                "Volunteer Account Creation Queue Error",
            )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def create_volunteer_from_member(
    member_name: str,
    volunteer_name: str | None = None,
    status="New",
    interested_skills=None,
    create_user_account=False,
    roles=None,
    role_profile=None,
):
    """Create a volunteer record from an existing member

    Args:
        member_name: Name of the Member record to create volunteer from
        volunteer_name: Optional custom volunteer name (defaults to member's full name)
        status: Initial volunteer status (default: "New")
        interested_skills: Optional list/string of skills the volunteer is interested in
        create_user_account: Whether to create user account via AccountCreationManager (default: False)
        roles: List of roles to assign if creating user account (default: ["Verenigingen Volunteer"])
        role_profile: Explicit Role Profile to assign to the user account (default: None, ACR infers from role)

    Returns:
        dict: Result with volunteer name if successful, error message if failed
    """
    try:
        # Validate member exists
        if not frappe.db.exists("Member", member_name):
            return {"success": False, "error": f"Member {member_name} does not exist"}

        # Check if volunteer already exists for this member
        existing_volunteer = get_volunteer_for_member(member_name)
        if existing_volunteer:
            return {
                "success": False,
                "error": f"Volunteer record already exists for member {member_name}: {existing_volunteer}",
            }

        # Get member data
        member = frappe.get_doc("Member", member_name)

        # Determine volunteer name
        if not volunteer_name:
            if member.full_name:
                volunteer_name = member.full_name
            elif getattr(member, "tussenvoegsel", None):  # the record answers it (#780)
                volunteer_name = format_dutch_full_name(
                    member.first_name, None, member.tussenvoegsel, member.last_name
                )
            else:
                volunteer_name = f"{member.first_name} {member.last_name}".strip()

        if not volunteer_name:
            volunteer_name = member.email or f"Volunteer-{member.name}"

        # Create volunteer record
        # Note: organization email is NOT set here - it will be assigned later
        # when the volunteer is given a system account
        volunteer_data = {
            "doctype": "Volunteer",
            "volunteer_name": volunteer_name,
            "member": member.name,
            "status": status,
            "start_date": member.member_since or frappe.utils.today(),
        }

        # Copy the user field from member if it exists
        if hasattr(member, "user") and member.user:
            volunteer_data["user"] = member.user
            frappe.logger().info(
                f"Copying existing user {member.user} from member {member.name} to volunteer"
            )

        # Add optional fields if available on Volunteer DocType
        if hasattr(member, "personal_email") and member.personal_email:
            volunteer_data["personal_email"] = member.personal_email

        volunteer = frappe.get_doc(volunteer_data)

        # Add skills if provided
        if interested_skills:
            if isinstance(interested_skills, str):
                try:
                    import json

                    interested_skills = json.loads(interested_skills)
                except json.JSONDecodeError as e:
                    frappe.log_error(
                        message=f"Failed to parse JSON skills data '{interested_skills}': {str(e)}",
                        title="Volunteer - JSON Parsing Error",
                        reference_doctype="Volunteer",
                        reference_name=volunteer_data.get("name", "New Volunteer"),
                    )
                    # Fallback to treating the string as a single skill
                    interested_skills = [interested_skills]
                except Exception as e:
                    frappe.log_error(
                        message=f"Unexpected error parsing skills data '{interested_skills}': {str(e)}",
                        title="Volunteer - Skills Parsing Error",
                        reference_doctype="Volunteer",
                        reference_name=volunteer_data.get("name", "New Volunteer"),
                    )
                    # Fallback to treating the string as a single skill
                    interested_skills = [interested_skills]

            if isinstance(interested_skills, list):
                for skill in interested_skills:
                    # Both shapes build the same row with the same fallbacks, so a bare
                    # skill name is just a dict with no category or level.
                    if isinstance(skill, str):
                        skill = {"name": skill}
                    if not isinstance(skill, dict):
                        continue
                    # category and level are free text out of the membership
                    # application; a value outside the Select's options fails the whole
                    # volunteer creation, not just the one skill row.
                    volunteer.append(
                        "skills_and_qualifications",
                        {
                            "volunteer_skill": skill.get("name", skill.get("skill", "Unknown")),
                            "skill_category": coerce_select_option(
                                "Volunteer Skill", "skill_category", skill.get("category"), "Other"
                            ),
                            "proficiency_level": coerce_select_option(
                                "Volunteer Skill", "proficiency_level", skill.get("level"), "1 - Beginner"
                            ),
                        },
                    )

        # Save volunteer with proper permissions - no bypasses
        # User must have proper permissions to create volunteer records
        volunteer.insert()

        # Security: Cross-document reference link from Volunteer to Member.
        # Uses db.set_value to update Member without triggering Member's validation
        # hooks. This is a simple reference link, not a business state change.
        # update_modified=False preserves Member's modification timestamp.
        frappe.db.set_value("Member", member_name, "volunteer_record", volunteer.name, update_modified=False)

        # Queue account creation if requested
        account_request_name = None
        if create_user_account:
            account_request_name = _queue_volunteer_account_creation(
                member_name=member_name, volunteer_name=volunteer.name, roles=roles, role_profile=role_profile
            )

        result = {
            "success": True,
            "volunteer_name": volunteer.name,
            "volunteer_display_name": volunteer.volunteer_name,
            "message": f"Successfully created volunteer record {volunteer.name} for member {member_name}",
        }

        if account_request_name:
            result["account_creation_queued"] = True
            result["account_request"] = account_request_name
            result["message"] += f". User account creation queued (request: {account_request_name})"

        return result

    except frappe.PermissionError as e:
        return {"success": False, "error": f"Permission denied: {str(e)}"}
    except frappe.ValidationError as e:
        return {"success": False, "error": f"Validation failed: {str(e)}"}
    except Exception as e:
        frappe.log_error(
            f"Error creating volunteer from member {member_name}: {str(e)}", "Volunteer Creation Error"
        )
        return {"success": False, "error": f"Failed to create volunteer: {str(e)}"}


def _queue_volunteer_account_creation(member_name, volunteer_name, roles=None, role_profile=None):
    """Queue account creation for volunteer via AccountCreationManager

    Args:
        member_name: Member record name
        volunteer_name: Volunteer record name
        roles: List of roles to assign (default: ["Verenigingen Volunteer"])
        role_profile: Explicit Role Profile to assign (default: None, ACR infers from role)

    Returns:
        str: Account Creation Request name if successful, None otherwise
    """
    try:
        from verenigingen.utils.account_creation_manager import queue_account_creation_for_member

        # Default roles for volunteers
        if not roles:
            roles = ["Verenigingen Volunteer"]
        elif isinstance(roles, str):
            import json

            try:
                roles = json.loads(roles)
            except json.JSONDecodeError:
                roles = [roles]

        # Queue account creation via centralized manager
        # Returns OperationResult or dict (if decorated function serializes it)
        result = queue_account_creation_for_member(
            member_name=member_name, roles=roles, role_profile=role_profile, priority="Normal"
        )

        # Handle both OperationResult (has .success) and dict (from decorator serialization)
        is_success = (
            result.success
            if hasattr(result, "success")
            else result.get("success", False)
            if isinstance(result, dict)
            else False
        )

        if result and is_success:
            data = result.data if hasattr(result, "data") else result.get("data", {})
            request_name = data.get("request_name") if data else None
            frappe.logger().info(
                f"Queued account creation for volunteer {volunteer_name} "
                f"(member: {member_name}, request: {request_name})"
            )
            return request_name
        else:
            error_msg = (
                result.error_message
                if hasattr(result, "error_message")
                else result.get("message", "Unknown error")
                if isinstance(result, dict)
                else "Unknown error"
            )
            frappe.logger().warning(
                f"Failed to queue account creation for volunteer {volunteer_name}: {error_msg}"
            )
            return None

    except Exception as e:
        frappe.log_error(
            f"Error queuing account creation for volunteer {volunteer_name}: {str(e)}",
            "Volunteer Account Creation Queue Error",
        )
        return None


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def search_volunteers_by_skill(skill_name: str, category=None, min_level=None):
    """Search volunteers by specific skill

    Args:
        skill_name: Skill name to search for (partial match)
        category: Optional skill category filter
        min_level: Optional minimum proficiency level filter

    Returns:
        List of volunteers with matching skills
    """
    conditions = ["v.status = 'Active'"]
    params = {"skill_name": f"%{skill_name}%"}

    if category:
        conditions.append("vs.skill_category = %(category)s")
        params["category"] = category

    if min_level:
        conditions.append("CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED) >= %(min_level)s")
        params["min_level"] = min_level

    volunteers = frappe.db.sql(
        """
        SELECT DISTINCT
            v.name,
            v.volunteer_name,
            v.status,
            vs.volunteer_skill as matched_skill,
            vs.proficiency_level,
            vs.skill_category
        FROM `tabVolunteer` v
        INNER JOIN `tabVolunteer Skill` vs ON vs.parent = v.name
        WHERE v.status = 'Active'
            AND vs.volunteer_skill LIKE %(skill_name)s
            {additional_conditions}
        ORDER BY
            CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED) DESC,
            v.volunteer_name
    """.format(
            additional_conditions=" AND " + " AND ".join(conditions[1:]) if len(conditions) > 1 else ""
        ),
        params,
        as_dict=True,
    )

    return volunteers


@frappe.whitelist()
@standard_api(operation_type=OperationType.PUBLIC)
def get_all_skills_list():
    """Get unique list of all skills for autocomplete and overview - cached for performance

    Returns:
        List of unique skills with usage statistics
    """
    # Delegates to the skill-query service (extracted to keep this controller
    # under the Controller Growth Prevention size limit).
    from verenigingen.services.volunteer.skill_query_service import get_all_skills_list_cached

    return get_all_skills_list_cached()


@frappe.whitelist()
@standard_api(operation_type=OperationType.PUBLIC)
def get_skill_suggestions(partial_skill):
    """Get skill suggestions for autocomplete

    Args:
        partial_skill: Partial skill name to search for

    Returns:
        List of skill names matching the partial input
    """
    if not partial_skill or len(partial_skill) < 2:
        return []

    suggestions = frappe.db.sql(
        """
        SELECT DISTINCT volunteer_skill, COUNT(*) as frequency
        FROM `tabVolunteer Skill`
        WHERE volunteer_skill LIKE %(partial)s
            AND volunteer_skill IS NOT NULL
            AND volunteer_skill != ''
        GROUP BY volunteer_skill
        ORDER BY frequency DESC, volunteer_skill
        LIMIT 10
    """,
        {"partial": f"%{partial_skill}%"},
        as_dict=True,
    )

    return [s.volunteer_skill for s in suggestions]


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_volunteers_with_filters(category=None, skill=None, min_level=None, max_results=50):
    """Get volunteers with skill-based filters

    Args:
        category: Optional skill category filter
        skill: Optional specific skill filter
        min_level: Optional minimum proficiency level
        max_results: Maximum number of results to return

    Returns:
        List of volunteers matching the filters
    """
    # Validate numeric inputs (whitelisted endpoints receive strings from web)
    try:
        max_results = min(int(max_results), 200)
    except (ValueError, TypeError):
        max_results = 50

    conditions = ["v.status = 'Active'"]
    params = {"max_results": max_results}

    join_clause = ""
    if skill or category or min_level:
        join_clause = "INNER JOIN `tabVolunteer Skill` vs ON vs.parent = v.name"

        if skill:
            conditions.append("vs.volunteer_skill LIKE %(skill)s")
            params["skill"] = f"%{skill}%"
        if category:
            conditions.append("vs.skill_category = %(category)s")
            params["category"] = category
        if min_level:
            try:
                params["min_level"] = int(min_level)
            except (ValueError, TypeError):
                params["min_level"] = 1
            conditions.append("CAST(LEFT(vs.proficiency_level, 1) AS UNSIGNED) >= %(min_level)s")

    # Build skills summary field based on whether we're joining skills table
    # Note: skills_field and join_clause are internal strings, not user input
    if join_clause:
        skills_field = (
            "GROUP_CONCAT(DISTINCT CONCAT(vs.volunteer_skill, ' (', vs.proficiency_level, ')')"
            " ORDER BY vs.skill_category, vs.volunteer_skill SEPARATOR ', ') as skills_summary"
        )
    else:
        skills_field = "NULL as skills_summary"

    where_clause = " AND ".join(conditions)

    # Query uses .format() only for structural parts (internal strings);
    # all user values go through %(...)s parameterization
    query = (
        "SELECT DISTINCT v.name, v.volunteer_name, v.status, v.email, "
        + skills_field
        + " FROM `tabVolunteer` v "
        + join_clause
        + " WHERE "
        + where_clause
        + " GROUP BY v.name ORDER BY v.volunteer_name LIMIT %(max_results)s"
    )

    volunteers = frappe.db.sql(query, params, as_dict=True)

    return volunteers


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_skill_insights():
    """Get skill insights for dashboard

    Returns:
        Dictionary with popular skills, skill gaps, and category distribution
    """
    # Most common skills
    popular_skills = frappe.db.sql(
        """
        SELECT volunteer_skill, skill_category, COUNT(*) as count
        FROM `tabVolunteer Skill` vs
        INNER JOIN `tabVolunteer` v ON vs.parent = v.name
        WHERE v.status = 'Active'
            AND vs.volunteer_skill IS NOT NULL
            AND vs.volunteer_skill != ''
        GROUP BY volunteer_skill, skill_category
        ORDER BY count DESC
        LIMIT 10
    """,
        as_dict=True,
    )

    # Skills by category (to identify gaps)
    category_distribution = frappe.db.sql(
        """
        SELECT
            skill_category,
            COUNT(DISTINCT parent) as volunteer_count,
            COUNT(*) as skill_count,
            AVG(CAST(LEFT(proficiency_level, 1) AS UNSIGNED)) as avg_proficiency
        FROM `tabVolunteer Skill` vs
        INNER JOIN `tabVolunteer` v ON vs.parent = v.name
        WHERE v.status = 'Active'
        GROUP BY skill_category
        ORDER BY volunteer_count DESC
    """,
        as_dict=True,
    )

    # High-level skills (Expert level)
    expert_skills = frappe.db.sql(
        """
        SELECT volunteer_skill, skill_category, COUNT(*) as expert_count
        FROM `tabVolunteer Skill` vs
        INNER JOIN `tabVolunteer` v ON vs.parent = v.name
        WHERE v.status = 'Active'
            AND vs.proficiency_level LIKE '5%'
        GROUP BY volunteer_skill, skill_category
        ORDER BY expert_count DESC
        LIMIT 5
    """,
        as_dict=True,
    )

    # Skills in development (from development goals)
    development_skills = frappe.db.sql(
        """
        SELECT skill, COUNT(*) as learner_count
        FROM `tabVolunteer Development Goal` vdg
        INNER JOIN `tabVolunteer` v ON vdg.parent = v.name
        WHERE v.status = 'Active'
            AND vdg.skill IS NOT NULL
            AND vdg.skill != ''
        GROUP BY skill
        ORDER BY learner_count DESC
        LIMIT 5
    """,
        as_dict=True,
    )

    return {
        "popular_skills": popular_skills,
        "category_distribution": category_distribution,
        "expert_skills": expert_skills,
        "development_skills": development_skills,
        "total_skills": len(get_all_skills_list()),
        "total_volunteers_with_skills": frappe.db.count(
            "Volunteer Skill", filters={"parenttype": "Volunteer"}
        ),
    }
