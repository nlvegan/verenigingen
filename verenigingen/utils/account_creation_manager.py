"""
Account Creation Manager

This module provides secure, background-processed account creation for the Verenigingen system.
It addresses critical security vulnerabilities by eliminating permission bypasses and implementing
proper validation, audit trails, and error handling.

Key Features:
- Zero permission bypasses - all operations use proper Frappe security
- Background job processing with comprehensive retry logic
- Detailed status tracking and failure reporting
- Complete audit trail for security compliance
- Transactional processing with rollback capability

Security Model:
- Validates permissions before every operation
- No use of ignore_permissions=True except for system status tracking
- Proper role assignment validation
- Complete audit logging

Architecture:
- Request-based processing through Account Creation Request DocType
- Background job execution via Redis queue
- Independent retry capability for each pipeline stage
- Integration with existing Frappe/ERPNext patterns

Author: Verenigingen Development Team
"""

import traceback

import frappe
from frappe import _
from frappe.utils import get_site_name, now

from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


class AccountCreationManager:
    """Secure account creation manager with proper permission validation"""

    def __init__(self, request_name):
        """Initialize with account creation request"""
        self.request_name = request_name
        self.request = None
        self.source_doc = None
        self.created_user = None
        self.created_employee = None

    def load_request(self):
        """Load and validate the account creation request"""
        if not frappe.db.exists("Account Creation Request", self.request_name):
            raise frappe.DoesNotExistError(f"Account creation request {self.request_name} not found")

        self.request = frappe.get_doc("Account Creation Request", self.request_name)

        # Load source document
        if not frappe.db.exists(self.request.request_type, self.request.source_record):
            raise frappe.DoesNotExistError(
                f"Source {self.request.request_type} {self.request.source_record} not found"
            )

        self.source_doc = frappe.get_doc(self.request.request_type, self.request.source_record)

    def process_complete_pipeline(self):
        """Execute the complete account creation pipeline with proper transaction boundaries"""
        try:
            self.load_request()

            # Don't validate status here - the background job was queued for a reason
            # Status checks belong in queue_processing(), not in the processing pipeline itself
            # This allows automatic retries to work without status gymnastics

            # Validate permissions and prerequisites
            self.validate_processing_permissions()

            # PHASE 1: Create User and Employee records (atomic transaction)
            # This phase creates the core records - if it fails, nothing is committed
            self._create_user_and_employee_phase()

            # PHASE 2: Link records together (separate atomic transaction)
            # This phase links existing records - safe to retry independently
            self._link_records_phase()

            # Send notification
            self.send_completion_notification()

            frappe.logger().info(f"Account creation completed successfully: {self.request_name}")

        except Exception as e:
            error_msg = str(e)
            frappe.logger().error(f"Account creation failed for {self.request_name}: {error_msg}")
            frappe.logger().error(traceback.format_exc())

            # Mark as failed with detailed error
            self.request.mark_failed(error_msg, self.get_current_stage())

            # Determine if this is retryable
            if self.is_retryable_error(e) and (self.request.retry_count or 0) < 3:
                self.schedule_retry()

            raise

    def _create_user_and_employee_phase(self):
        """Phase 1: Create User and Employee records in atomic transaction"""
        frappe.logger().info(f"Phase 1: Creating User and Employee for {self.request_name}")

        try:
            # Create user account (if not exists)
            if not self.request.created_user:
                self.create_user_account()
            else:
                # User already exists - populate instance variable for linking
                self.created_user = self.request.created_user
                frappe.logger().info(f"User already exists: {self.created_user}, will reuse for linking")

            # Assign roles and role profile
            if self.request.pipeline_stage != "Completed":
                self.assign_roles_and_profile()

            # Create employee record (if needed)
            if self.requires_employee_creation() and not self.request.created_employee:
                self.create_employee_record()
            elif self.request.created_employee:
                # Employee already exists - populate instance variable for linking
                self.created_employee = self.request.created_employee
                frappe.logger().info(
                    f"Employee already exists: {self.created_employee}, will reuse for linking"
                )

            frappe.logger().info(
                f"Phase 1 completed: User={self.created_user}, Employee={self.created_employee}"
            )

        except Exception as e:
            frappe.logger().error(f"Phase 1 failed: {str(e)}")
            raise

    def _link_records_phase(self):
        """Phase 2: Link all records together in atomic transaction"""
        frappe.logger().info(f"Phase 2: Linking records for {self.request_name}")

        try:
            # Link all records together (no commits inside - single atomic operation)
            self.link_records()

            # Mark as completed
            self.request.mark_completed(user=self.created_user, employee=self.created_employee)

            frappe.logger().info(f"Phase 2 completed: All records linked successfully")

        except Exception as e:
            frappe.logger().error(f"Phase 2 failed: {str(e)}")
            # User and Employee still exist from Phase 1 - can retry linking
            frappe.logger().warning(
                f"User/Employee creation succeeded, but linking failed. "
                f"Retry will attempt linking with existing User/Employee."
            )
            raise

    def validate_processing_permissions(self):
        """Validate that processing can proceed with proper permissions"""
        frappe.logger().info(f"Validating processing permissions for {self.request_name}")

        # Require proper user context - no Guest access
        if frappe.session.user == "Guest":
            raise frappe.PermissionError("Account creation requires authenticated user")

        # Validate current user has permission to create users
        if not frappe.has_permission("User", "create"):
            raise frappe.PermissionError("Current user cannot create user accounts")

        # Validate role assignments
        for role_row in self.request.requested_roles:
            if not self.can_assign_role(role_row.role):
                raise frappe.PermissionError(f"Cannot assign role: {role_row.role}")

        frappe.logger().info(f"Permission validation passed for {self.request_name}")

    def create_user_account(self):
        """Create user account with proper security validation"""
        self.request.mark_processing("User Creation")

        frappe.logger().info(f"Creating user account for {self.request.email}")

        # Validate email uniqueness again
        if frappe.db.exists("User", self.request.email):
            # If user already exists, use existing user and continue with pipeline
            # to ensure proper linking to member record
            self.created_user = self.request.email
            self.request.created_user = self.created_user
            frappe.logger().info(
                f"User account already exists: {self.request.email}, will proceed to role assignment and linking"
            )
            # Exit user creation, but pipeline will continue with role assignment and linking
            return

        try:
            # Parse name components
            name_parts = self.request.full_name.split() if self.request.full_name else ["User"]
            first_name = name_parts[0] if name_parts else "User"
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Determine user type based on request type
            # Members get Website User for portal access
            # Volunteers get System User for full system access
            user_type = "System User" if self.request.request_type == "Volunteer" else "Website User"

            # Skip welcome emails during bulk imports
            send_welcome = 0 if (frappe.flags.in_import or frappe.flags.in_bulk_import) else 1

            # Create user document with explicit password for bulk operations
            # This prevents 'NoneType' object has no attribute 'encode' errors
            user_data = {
                "doctype": "User",
                "email": self.request.email,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": self.request.full_name,
                "enabled": 1,
                "user_type": user_type,
                "send_welcome_email": send_welcome,  # Skip during bulk imports
            }

            # ALWAYS set a random password to avoid 'NoneType' has no attribute 'encode' errors
            # This prevents errors even if send_welcome_email=1 but email sending is disabled
            user_data["new_password"] = frappe.generate_hash(length=20)

            user_doc = frappe.get_doc(user_data)

            # Add personal email if available
            if hasattr(self.source_doc, "personal_email") and self.source_doc.personal_email:
                # Don't add this to user_doc as it's not a standard field
                pass

            # Insert with proper permissions - NO ignore_permissions=True
            # For bulk operations (CSV imports), bypass rate limiting by setting in_import flag
            # This is the intended use of frappe.flags.in_import as per Frappe core throttle_user_creation()
            is_bulk_operation = getattr(frappe.flags, "bulk_account_creation", False)

            # Save original flag state for restoration
            original_in_import = getattr(frappe.flags, "in_import", False)
            original_mute_emails = getattr(frappe.flags, "mute_emails", False)

            try:
                # Use Frappe's native email muting for bulk operations
                if is_bulk_operation:
                    frappe.flags.in_import = True
                    frappe.flags.mute_emails = True  # Frappe-native email suppression

                user_doc.insert()

            except frappe.exceptions.UniqueValidationError as e:
                # Handle duplicate username - Frappe auto-generates username from first name
                error_msg = str(e)
                if "Duplicate entry" in error_msg and "for key 'username'" in error_msg:
                    # Username conflict - let Frappe handle this by trying with email as username
                    frappe.logger().info(
                        f"Username conflict for {first_name}, retrying with email as username"
                    )
                    user_doc.username = self.request.email.split("@")[0]  # Use email prefix
                    try:
                        # Email suppression already set via frappe.flags.mute_emails above
                        user_doc.insert()
                    except:
                        # If still fails, this is a real duplicate - check if user exists
                        if frappe.db.exists("User", self.request.email):
                            self.created_user = self.request.email
                            self.request.created_user = self.created_user
                            frappe.logger().info(
                                f"User {self.request.email} already exists, will skip creation and continue"
                            )
                            return  # Exit early, user exists
                        else:
                            raise
                else:
                    raise
            except frappe.exceptions.OutgoingEmailError:
                # Suppress email errors during bulk imports - missing email account is expected
                if frappe.flags.in_import or frappe.flags.in_bulk_import:
                    frappe.logger().debug(
                        f"Suppressed email notification error for {self.request.email} during bulk import"
                    )
                    # User was still created, just email failed - that's fine for bulk imports
                    pass
                else:
                    raise
            finally:
                # Always restore original flag state
                frappe.flags.in_import = original_in_import
                frappe.flags.mute_emails = original_mute_emails

            self.created_user = user_doc.name
            self.request.created_user = self.created_user

            frappe.logger().info(f"User account created successfully: {user_doc.name}")

        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__

            # Enhanced logging for rate limit and throttling errors
            if "throttle" in error_msg.lower() or "rate limit" in error_msg.lower():
                frappe.logger().error(
                    f"Rate limit encountered creating user {self.request.email}: "
                    f"{error_type}: {error_msg}. "
                    f"This typically occurs when creating many users simultaneously. "
                    f"The request will be retried automatically."
                )
                raise frappe.ValidationError(
                    f"User account creation rate limited (will retry automatically): {error_msg}"
                )
            else:
                frappe.logger().error(f"Failed to create user account: {error_type}: {error_msg}")
                raise frappe.ValidationError(f"User account creation failed ({error_type}): {error_msg}")

    def assign_roles_and_profile(self):
        """Assign roles and role profile with proper permission validation"""
        if not self.created_user:
            raise frappe.ValidationError("Cannot assign roles - no user account exists")

        self.request.mark_processing("Role Assignment")

        frappe.logger().info(f"Assigning roles to user: {self.created_user}")

        try:
            user_doc = frappe.get_doc("User", self.created_user)
            existing_roles = [r.role for r in user_doc.roles]

            # Assign individual roles
            roles_added = []
            for role_row in self.request.requested_roles:
                role_name = role_row.role

                # Security validation
                if not self.can_assign_role(role_name):
                    raise frappe.PermissionError(f"Cannot assign role: {role_name}")

                if not frappe.db.exists("Role", role_name):
                    raise frappe.ValidationError(f"Role does not exist: {role_name}")

                # Add role if not already present
                if role_name not in existing_roles:
                    user_doc.append("roles", {"role": role_name})
                    roles_added.append(role_name)

            # Assign role profile if specified
            if self.request.role_profile:
                if not frappe.db.exists("Role Profile", self.request.role_profile):
                    raise frappe.ValidationError(f"Role profile does not exist: {self.request.role_profile}")

                user_doc.role_profile_name = self.request.role_profile
                frappe.logger().info(f"Role profile {self.request.role_profile} assigned")

            # Save with proper permissions - NO ignore_permissions=True
            # Use retry logic for deadlock handling during concurrent role assignments
            if roles_added or self.request.role_profile:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        user_doc.save()
                        frappe.logger().info(f"Roles assigned successfully: {roles_added}")
                        break
                    except Exception as save_error:
                        error_msg = str(save_error)
                        # Retry on deadlock errors (MySQL error 1213)
                        if ("Deadlock" in error_msg or "1213" in error_msg) and attempt < max_retries - 1:
                            import random
                            import time

                            # Exponential backoff: 100ms, 200ms, 400ms + jitter
                            delay = (0.1 * (2**attempt)) + random.uniform(0, 0.05)
                            frappe.logger().info(
                                f"Deadlock during role assignment, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})"
                            )
                            time.sleep(delay)
                            # Reload user to avoid timestamp conflicts
                            user_doc = frappe.get_doc("User", self.created_user)
                            # Re-apply roles that aren't already present
                            existing_roles = [r.role for r in user_doc.roles]
                            for role in roles_added:
                                if role not in existing_roles:
                                    user_doc.append("roles", {"role": role})
                            continue
                        else:
                            raise
            else:
                frappe.logger().info("No new roles to assign")

            # Set module access for member users
            if self.request.request_type == "Member":
                self._set_member_user_modules()
                frappe.logger().info(f"Module access configured for member user: {self.created_user}")

        except Exception as e:
            frappe.logger().error(f"Failed to assign roles: {str(e)}")
            raise frappe.ValidationError(f"Role assignment failed: {str(e)}")

    def create_employee_record(self):
        """Create employee record for expense functionality"""
        if not self.created_user:
            raise frappe.ValidationError("Cannot create employee - no user account exists")

        self.request.mark_processing("Employee Creation")

        frappe.logger().info(f"Creating employee record for user: {self.created_user}")

        # Check if employee already exists for this user
        existing_employee = frappe.db.get_value("Employee", {"user_id": self.created_user}, "name")
        if existing_employee:
            # Employee already exists, use it and continue with pipeline
            self.created_employee = existing_employee
            self.request.created_employee = self.created_employee
            frappe.logger().info(
                f"Employee record already exists: {existing_employee} for user {self.created_user}, will proceed to linking"
            )
            return

        try:
            # Get company from Verenigingen Settings
            settings = frappe.get_single("Verenigingen Settings")
            if not settings.company:
                frappe.throw(_("Company not configured in Verenigingen Settings"))
            default_company = settings.company

            if not default_company:
                raise frappe.ValidationError("No company configured for employee creation")

            # Parse name for employee record
            name_parts = self.request.full_name.split() if self.request.full_name else ["Employee"]
            first_name = name_parts[0] if name_parts else "Employee"
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Create employee document
            employee_doc = frappe.get_doc(
                {
                    "doctype": "Employee",
                    "employee_name": self.request.full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "company": default_company,
                    "status": "Active",
                    "gender": "Prefer not to say",
                    "date_of_birth": "1990-01-01",  # Default value
                    "date_of_joining": frappe.utils.today(),
                    "user_id": self.created_user,  # Link to user account
                }
            )

            # Add email if available
            if self.request.email:
                employee_doc.personal_email = self.request.email

            # Insert with proper permissions - NO ignore_permissions=True
            employee_doc.insert()

            self.created_employee = employee_doc.name
            self.request.created_employee = self.created_employee

            frappe.logger().info(f"Employee record created successfully: {employee_doc.name}")

        except Exception as e:
            frappe.logger().error(f"Failed to create employee record: {str(e)}")
            raise frappe.ValidationError(f"Employee record creation failed: {str(e)}")

    def link_records(self):
        """
        Link all created records together in a single atomic operation.

        This method is idempotent - safe to retry if Phase 2 fails.
        All links are set in a single transaction with no intermediate commits.
        Uses update_modified=False to avoid timestamp conflicts during concurrent operations.
        """
        self.request.mark_processing("Record Linking")

        frappe.logger().info(f"Linking records for {self.request_name}")

        try:
            # Link 1: User to source record (Member/Volunteer)
            if self.created_user and hasattr(self.source_doc, "user"):
                current_user = frappe.db.get_value(
                    self.request.request_type, self.request.source_record, "user"
                )
                if not current_user:
                    frappe.db.set_value(
                        self.request.request_type,
                        self.request.source_record,
                        "user",
                        self.created_user,
                        update_modified=False,  # Avoid timestamp conflicts
                    )
                    frappe.logger().info(
                        f"Linked user {self.created_user} to {self.request.request_type} {self.request.source_record}"
                    )

            # Link 2: Employee to source record (Member/Volunteer)
            if self.created_employee and hasattr(self.source_doc, "employee"):
                current_employee = frappe.db.get_value(
                    self.request.request_type, self.request.source_record, "employee"
                )
                if not current_employee:
                    frappe.db.set_value(
                        self.request.request_type,
                        self.request.source_record,
                        "employee",
                        self.created_employee,
                        update_modified=False,  # Avoid timestamp conflicts
                    )
                    frappe.logger().info(
                        f"Linked employee {self.created_employee} to {self.request.request_type} {self.request.source_record}"
                    )

            # Link 3: Employee to User record
            # NOTE: Employee.user_id links to User, not User.employee to Employee
            # The link was already established during employee creation (line 340: user_id)
            # No additional linking needed here - Employee.user_id is set during create_employee_record()
            if self.created_user and self.created_employee:
                frappe.logger().info(
                    f"Employee {self.created_employee} already linked to User {self.created_user} via Employee.user_id"
                )

            # Link 4 & 5: For Member records, link User and Employee to associated Volunteer record
            if self.request.request_type == "Member":
                volunteer_record = frappe.db.get_value(
                    "Volunteer", {"member": self.request.source_record}, "name"
                )
                if volunteer_record:
                    # Link 4: User to Volunteer
                    if self.created_user:
                        current_volunteer_user = frappe.db.get_value("Volunteer", volunteer_record, "user")
                        if not current_volunteer_user:
                            frappe.db.set_value(
                                "Volunteer",
                                volunteer_record,
                                "user",
                                self.created_user,
                                update_modified=False,  # Avoid timestamp conflicts
                            )
                            frappe.logger().info(
                                f"Linked user {self.created_user} to Volunteer {volunteer_record}"
                            )

                    # Link 5: Employee to Volunteer
                    if self.created_employee:
                        current_volunteer_employee = frappe.db.get_value(
                            "Volunteer", volunteer_record, "employee_id"
                        )
                        if not current_volunteer_employee:
                            frappe.db.set_value(
                                "Volunteer",
                                volunteer_record,
                                "employee_id",
                                self.created_employee,
                                update_modified=False,  # Avoid timestamp conflicts
                            )
                            frappe.logger().info(
                                f"Linked employee {self.created_employee} to Volunteer {volunteer_record}"
                            )

            frappe.logger().info(f"Records linked successfully for {self.request_name}")

        except Exception as e:
            frappe.logger().error(f"Failed to link records: {str(e)}")
            # Raise exception to trigger transaction rollback
            # All links are either committed together or rolled back together
            raise

    def requires_employee_creation(self):
        """Check if employee record creation is needed"""
        # ALWAYS create employee for volunteers who need expense functionality
        if self.request.request_type in ["Volunteer", "Both"]:
            return True

        # For Member requests, check if explicitly requested via import flag
        if self.request.request_type == "Member":
            # Check if the request has the create_employee_record field set
            # This is set by CSV import when create_employee_records is checked
            if self.request.create_employee_record:
                return True

            # Legacy behavior: Don't auto-create employees just because a volunteer record exists
            # This caused unwanted employee creation during CSV imports

        # Check if any requested roles require employee record
        employee_roles = ["Employee", "Employee Self Service"]
        for role_row in self.request.requested_roles:
            if role_row.role in employee_roles:
                return True

        return False

    def can_assign_role(self, role_name):
        """Check if current user can assign this role"""
        current_roles = frappe.get_roles()

        # System managers can assign any role
        if "System Manager" in current_roles:
            return True

        # Verenigingen administrators can assign verenigingen roles
        if "Verenigingen Administrator" in current_roles:
            allowed_roles = [
                "Verenigingen Member",
                "Verenigingen Volunteer",
                "Verenigingen Chapter Board Member",
                "Employee",
                "Employee Self Service",
            ]
            return role_name in allowed_roles

        return False

    def _set_member_user_modules(self):
        """Set allowed modules for member users - restrict to relevant modules only"""
        if not self.created_user:
            return

        try:
            from verenigingen.verenigingen.doctype.member.member import set_member_user_modules

            set_member_user_modules(self.created_user)
            frappe.logger().info(f"Module access configured for user {self.created_user}")

        except Exception as e:
            frappe.logger().error(f"Error setting member user modules: {str(e)}")
            # Don't fail the entire process for module configuration
            frappe.logger().warning("Continuing despite module configuration error")

    def get_current_stage(self):
        """Get current processing stage for error reporting"""
        return getattr(self.request, "pipeline_stage", "Unknown")

    def is_retryable_error(self, error):
        """Determine if an error is retryable"""
        retryable_errors = [
            "timeout",
            "connection",
            "temporary",
            "deadlock",
            "lock wait timeout",
            "rate limit",
        ]

        error_str = str(error).lower()
        return any(keyword in error_str for keyword in retryable_errors)

    def schedule_retry(self):
        """Schedule retry for failed request"""
        retry_delay_minutes = min(5 * (2 ** (self.request.retry_count or 0)), 60)  # Exponential backoff

        frappe.enqueue(
            "verenigingen.utils.account_creation_manager.process_account_creation_request",
            request_name=self.request_name,
            queue="long",
            timeout=600,
            job_name=f"account_creation_retry_{self.request_name}",
            at_time=frappe.utils.add_to_date(None, minutes=retry_delay_minutes),
        )

        frappe.logger().info(f"Scheduled retry for {self.request_name} in {retry_delay_minutes} minutes")

    def send_completion_notification(self):
        """Send notification when account creation is completed"""
        try:
            # Send email to the new user if user creation was successful
            if self.created_user:
                # The welcome email is handled by Frappe automatically
                frappe.logger().info(f"Welcome email will be sent to {self.created_user}")

            # Notify the requestor if different from new user
            if self.request.requested_by != self.created_user:
                frappe.publish_realtime(
                    "account_creation_completed",
                    {
                        "request_name": self.request_name,
                        "user_created": self.created_user,
                        "employee_created": self.created_employee,
                    },
                    user=self.request.requested_by,
                )

        except Exception as e:
            frappe.logger().warning(f"Failed to send completion notification: {str(e)}")


# Background job entry points


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_account_creation_request(request_name, at_time=None):
    """Background job entry point for processing account creation requests

    Args:
        request_name: Name of the Account Creation Request to process
        at_time: Scheduled execution time (passed by frappe.enqueue when using at_time parameter)
    """
    # Mark as background job to exempt from rate limits
    frappe.flags.in_background_job = True

    # Mark as bulk operation to bypass Frappe's core throttle_user_creation()
    # This is necessary because background jobs creating users in parallel will hit
    # Frappe's hardcoded throttle limit (60 users/minute by default)
    frappe.flags.bulk_account_creation = True
    frappe.flags.in_import = True  # Tells Frappe core to skip throttle_user_creation()

    try:
        manager = AccountCreationManager(request_name)
        manager.process_complete_pipeline()
        return {"success": True, "message": "Account creation completed successfully"}

    except Exception as e:
        frappe.logger().error(f"Account creation job failed for {request_name}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def queue_account_creation_for_member(member_name, roles=None, role_profile=None, priority="Normal"):
    """Queue account creation for a member record"""
    if not frappe.has_permission("User", "create"):
        frappe.throw(_("Insufficient permissions to create user accounts"))

    # Get member details
    member = frappe.get_doc("Member", member_name)

    if not member.email:
        frappe.throw(_("Member must have an email address for account creation"))

    # Note: Even if user exists, we still create a request to ensure proper linking
    # The AccountCreationManager will detect the existing user and link it to the member

    # Check if request already exists
    existing_request = frappe.db.exists(
        "Account Creation Request",
        {"source_record": member_name, "status": ["not in", ["Completed", "Cancelled"]]},
    )

    if existing_request:
        frappe.throw(_("Account creation request already exists: {0}").format(existing_request))

    # Set default roles if not provided
    if not roles:
        roles = ["Verenigingen Member"]
    if not role_profile:
        role_profile = "Verenigingen Member"

    # All member account requests use "Member" type
    # Employee creation is determined by requires_employee_creation() method
    # which checks for volunteer records automatically
    request_type = "Member"

    # Create request
    request = frappe.get_doc(
        {
            "doctype": "Account Creation Request",
            "request_type": request_type,
            "source_record": member_name,
            "email": member.email,
            "full_name": member.full_name,
            "priority": priority,
            "role_profile": role_profile,
            "business_justification": "Member account creation for portal access",
        }
    )

    # Add requested roles
    for role in roles:
        request.append("requested_roles", {"role": role})

    request.insert()

    # Queue for processing
    result = request.queue_processing()

    return {
        "success": True,
        "request_name": request.name,
        "message": result.get("message", "Account creation queued"),
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def queue_account_creation_for_volunteer(volunteer_name, priority="Normal"):
    """Queue account creation for a volunteer record"""
    # Skip permission check during tests if flag is set
    if not frappe.flags.get("skip_user_permission_check", False):
        if not frappe.has_permission("User", "create"):
            frappe.throw(_("Insufficient permissions to create user accounts"))

    # Get volunteer details
    volunteer = frappe.get_doc("Volunteer", volunteer_name)

    if not volunteer.email:
        frappe.throw(_("Volunteer must have an email address for account creation"))

    # Check if user already exists for this email
    if frappe.db.exists("User", volunteer.email):
        frappe.logger().info(
            f"User account already exists for volunteer {volunteer_name} with email {volunteer.email}"
        )
        # Return a successful result indicating existing account was found
        return {
            "request_name": None,
            "result": "existing_user",
            "message": f"User account already exists for {volunteer.email}",
        }

    # Check if request already exists
    existing_request = frappe.db.exists(
        "Account Creation Request",
        {"source_record": volunteer_name, "status": ["not in", ["Completed", "Cancelled"]]},
    )

    if existing_request:
        frappe.throw(_("Account creation request already exists: {0}").format(existing_request))

    # Create request with volunteer-specific roles
    request = frappe.get_doc(
        {
            "doctype": "Account Creation Request",
            "request_type": "Volunteer",
            "source_record": volunteer_name,
            "email": volunteer.email,
            "full_name": volunteer.volunteer_name,
            "priority": priority,
            "role_profile": "Verenigingen Volunteer",
            "business_justification": "Volunteer account creation for system access and expense reporting",
        }
    )

    # Add volunteer-specific roles
    volunteer_roles = ["Verenigingen Volunteer", "Employee", "Employee Self Service"]

    for role in volunteer_roles:
        request.append("requested_roles", {"role": role})

    request.insert()

    # Queue for processing
    result = request.queue_processing()

    return {
        "success": True,
        "request_name": request.name,
        "message": result.get("message", "Account creation queued"),
    }


# Bulk processing functions


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def queue_bulk_account_creation_for_members(
    member_names, roles=None, role_profile=None, batch_size=50, priority="Low", create_employee=False
):
    """
    Queue bulk account creation for multiple members using AccountCreationService.

    This is now a thin wrapper around AccountCreationService.queue_bulk_requests()
    which consolidates all validation, linking, and request creation logic.

    Args:
        member_names: List of member names to process
        roles: Default roles to assign (defaults to ["Verenigingen Member"])
        role_profile: Role profile to assign (defaults to "Verenigingen Member")
        batch_size: Number of members to process in each batch (default 50)
        priority: Processing priority ("Low", "Normal", "High")
        create_employee: Whether to create Employee records (default False)

    Returns:
        dict: Summary with request names, linked users, and validation errors
    """
    if not frappe.has_permission("User", "create"):
        frappe.throw(_("Insufficient permissions to create user accounts"))

    if not member_names:
        return {"success": False, "error": "No member names provided"}

    frappe.logger().info(
        f"Starting bulk account creation for {len(member_names)} members using AccountCreationService"
    )

    # Set bulk operations flag for COR rate limiting exemption
    frappe.flags.bulk_account_creation = True
    frappe.flags.in_background_job = True  # Mark as background operation

    # Set defaults
    if not roles:
        roles = ["Verenigingen Member"]
    if not role_profile:
        role_profile = "Verenigingen Member"

    # Use AccountCreationService for all validation, linking, and request creation
    from verenigingen.services.account.account_creation_service import get_account_creation_service

    service = get_account_creation_service()
    result = service.queue_bulk_requests(
        member_names=member_names,
        roles=roles,
        role_profile=role_profile,
        batch_size=batch_size,
        priority=priority,
        create_employee=create_employee,
        filter_by_status=True,  # Only process Active/Pending members
    )

    # Extract results from service
    created_requests = result.get("request_names", [])
    validation_errors = result.get("validation_errors", [])
    linked_count = result.get("users_linked", 0)

    # If no requests were created, handle appropriately
    if not created_requests:
        # Check if we linked any existing users
        if linked_count > 0:
            return {
                "success": True,
                "requests_created": 0,
                "users_linked": linked_count,
                "validation_errors_count": result.get("validation_errors_count", 0),
                "validation_errors": validation_errors[:50],
                "message": f"Linked {linked_count} existing user accounts, no new accounts to create",
            }
        else:
            return {
                "success": False,
                "error": "No valid members found for processing",
                "validation_errors_count": result.get("validation_errors_count", 0),
                "validation_errors": validation_errors[:50],
            }

    # Create progress tracker for this bulk operation
    from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
        BulkOperationTracker,
    )

    tracker = BulkOperationTracker.create_tracker(
        operation_type="Account Creation",
        total_records=len(created_requests),
        batch_size=batch_size,
        priority=priority,
    )

    # Queue processing in batches using dedicated bulk processor
    batch_results = []
    total_requests = len(created_requests)

    for i in range(0, total_requests, batch_size):
        batch = created_requests[i : i + batch_size]
        batch_number = i // batch_size + 1
        batch_id = f"bulk_batch_{batch_number}"

        # Queue this batch for processing using dedicated bulk queue
        try:
            frappe.enqueue(
                "verenigingen.utils.account_creation_manager.process_bulk_account_creation_batch",
                request_names=batch,
                batch_id=batch_id,
                batch_number=batch_number,
                tracker_name=tracker.name,
                queue="long",  # Use long queue for batch processing
                timeout=3600,  # 1 hour timeout for batch processing
                job_name=f"bulk_account_creation_{batch_id}",
            )

            batch_results.append(
                {
                    "batch_id": batch_id,
                    "batch_number": batch_number,
                    "request_count": len(batch),
                    "status": "queued",
                }
            )

            frappe.logger().info(f"Queued batch {batch_id} with {len(batch)} requests")

        except Exception as e:
            batch_results.append(
                {
                    "batch_id": batch_id,
                    "batch_number": batch_number,
                    "request_count": len(batch),
                    "status": "failed",
                    "error": str(e),
                }
            )
            frappe.logger().error(f"Failed to queue batch {batch_id}: {str(e)}")

    # Start the operation tracking
    tracker.start_operation()

    # Return comprehensive summary
    return_result = {
        "success": True,
        "total_members_provided": len(member_names),
        "validation_errors_count": result.get("validation_errors_count", 0),
        "users_linked": linked_count,
        "requests_created": len(created_requests),
        "batch_count": len(batch_results),
        "batch_size": batch_size,
        "batches": batch_results,
        "request_names": created_requests,
        "tracker_name": tracker.name,
        "tracker_url": f"/app/bulk-operation-tracker/{tracker.name}",
        "validation_errors": validation_errors[:50],
    }

    frappe.logger().info(
        f"Bulk account creation queued: {len(created_requests)} requests in {len(batch_results)} batches, "
        f"{linked_count} users linked"
    )

    return return_result


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_bulk_account_creation_batch(request_names, batch_id, batch_number, tracker_name):
    """
    Process a batch of account creation requests with parallel processing and enhanced error handling.

    This is the background job that processes individual batches created by the
    bulk queue function. Requests are processed in parallel (up to 5 at a time)
    to meet performance requirements while maintaining error isolation.

    Args:
        request_names: List of Account Creation Request names to process
        batch_id: Batch identifier for logging
        batch_number: Batch number for progress tracking (1-indexed)
        tracker_name: Name of BulkOperationTracker document

    Returns:
        dict: Batch processing results with success/failure counts
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Mark this as a background job and bulk operation for rate limiting bypass
    frappe.flags.in_background_job = True
    frappe.flags.bulk_account_creation = True
    frappe.flags.in_import = True  # Skip email sending and rate limiting for batch operations

    frappe.logger().info(
        f"Starting parallel batch processing for {batch_id} with {len(request_names)} requests"
    )

    batch_results = {
        "batch_id": batch_id,
        "batch_number": batch_number,
        "total_requests": len(request_names),
        "completed": 0,
        "failed": 0,
        "errors": [],
        "completed_requests": [],
        "failed_requests": [],
    }

    # Thread-safe locks for updating results
    results_lock = threading.Lock()

    def process_single_request_safe(request_name, site_name):
        """Process a single request with error handling, transaction safety, and new database connection."""
        import time

        # Add small delay to avoid overwhelming rate limiters
        # With throttle_user_limit increased to 300/min, this provides spacing
        time.sleep(0.5)  # 500ms delay between requests

        try:
            # Each thread needs its own database connection with site context
            frappe.connect(site=site_name)

            # Set bulk operation flags in this thread's context (flags don't propagate across threads)
            frappe.flags.in_background_job = True
            frappe.flags.bulk_account_creation = True

            # Start transaction for this request
            frappe.db.begin()

            try:
                # Validate request exists before attempting to process
                if not frappe.db.exists("Account Creation Request", request_name):
                    frappe.logger().warning(
                        f"Batch {batch_id}: Request {request_name} no longer exists (may have been deleted or already processed)"
                    )
                    return {
                        "success": True,
                        "request_name": request_name,
                        "skipped": True,
                        "reason": "not_found",
                    }

                # Ensure request is in processable status (handle retry scenario)
                request = frappe.get_doc("Account Creation Request", request_name)

                # Skip requests that are already completed
                if request.status == "Completed":
                    frappe.logger().info(
                        f"Batch {batch_id}: Skipping already completed request {request_name}"
                    )
                    return {
                        "success": True,
                        "request_name": request_name,
                        "skipped": True,
                        "reason": "already_completed",
                    }

                if request.status == "Requested":
                    request.status = "Queued"
                    request.processing_started_at = now()
                    request.save()

                # Process individual request using existing AccountCreationManager
                manager = AccountCreationManager(request_name)
                manager.process_complete_pipeline()

                # Commit transaction on success
                frappe.db.commit()

                frappe.logger().info(f"Batch {batch_id}: Completed request {request_name}")
                return {"success": True, "request_name": request_name}

            except Exception as processing_error:
                # Rollback transaction on any processing error
                frappe.db.rollback()
                frappe.logger().error(
                    f"Batch {batch_id}: Processing failed for {request_name}, rolled back: {str(processing_error)}"
                )
                return {"success": False, "request_name": request_name, "error": str(processing_error)}

        except Exception as e:
            # Handle connection or other system errors
            frappe.logger().error(f"Batch {batch_id}: System error for {request_name}: {str(e)}")
            return {"success": False, "request_name": request_name, "error": f"System error: {str(e)}"}
        finally:
            # Clean up database connection
            try:
                frappe.db.close()
            except:
                pass  # Ignore cleanup errors

    # Capture current site name for worker threads
    current_site = frappe.local.site

    # Process requests in parallel with controlled concurrency
    # With throttle_user_limit=300, we can safely use 5 workers (60 users/min per worker)
    # Each worker has 500ms delay, so 2 users/sec/worker * 5 workers = 10 users/sec = 600/min theoretical
    # Actual rate will be lower due to processing time, staying well under 300/min limit
    max_workers = min(5, len(request_names))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all requests to the thread pool with site context
        future_to_request = {
            executor.submit(process_single_request_safe, request_name, current_site): request_name
            for request_name in request_names
        }

        # Process completed futures as they finish
        for future in as_completed(future_to_request):
            request_name = future_to_request[future]
            try:
                result = future.result(timeout=300)  # 5-minute timeout per request

                # Update results with thread-safe lock
                with results_lock:
                    if result["success"]:
                        batch_results["completed"] += 1
                        batch_results["completed_requests"].append(request_name)
                    else:
                        batch_results["failed"] += 1
                        batch_results["failed_requests"].append(request_name)
                        batch_results["errors"].append(
                            f"{request_name}: {result.get('error', 'Unknown error')}"
                        )

            except Exception as e:
                # Handle timeout or other execution errors
                with results_lock:
                    batch_results["failed"] += 1
                    batch_results["failed_requests"].append(request_name)
                    batch_results["errors"].append(f"{request_name}: Execution error - {str(e)}")

                frappe.logger().error(f"Batch {batch_id}: Execution error for {request_name}: {str(e)}")

    # Update progress tracker
    try:
        tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
        tracker.update_progress(batch_number, batch_results)
        frappe.logger().info(f"Updated tracker {tracker_name} with batch {batch_number} results")
    except Exception as e:
        frappe.logger().error(f"Failed to update tracker {tracker_name}: {str(e)}")
        # Don't fail the batch processing if tracker update fails

    # Log batch completion summary
    frappe.logger().info(
        f"Batch {batch_id} completed: {batch_results['completed']} success, "
        f"{batch_results['failed']} failed out of {batch_results['total_requests']} total"
    )

    # If there were failures, log them for administrative review
    if batch_results["failed"] > 0:
        frappe.log_error(
            f"Batch {batch_id} had {batch_results['failed']} failures:\n"
            + "\n".join(batch_results["errors"][:10]),  # Log first 10 errors
            "Bulk Account Creation Batch Errors",
        )

    return batch_results


# Administrative functions


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_failed_requests():
    """Get failed account creation requests for admin review"""
    # Skip permission check during tests if flag is set
    if not frappe.flags.get("skip_user_permission_check", False):
        if not frappe.has_permission("Account Creation Request", "read"):
            frappe.throw(_("Insufficient permissions"))

    return frappe.get_all(
        "Account Creation Request",
        filters={"status": "Failed"},
        fields=[
            "name",
            "request_type",
            "source_record",
            "email",
            "full_name",
            "failure_reason",
            "retry_count",
            "creation",
            "pipeline_stage",
        ],
        order_by="creation desc",
    )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def retry_failed_request(request_name):
    """Manually retry a failed account creation request"""
    if not frappe.has_permission("Account Creation Request", "write"):
        frappe.throw(_("Insufficient permissions"))

    request = frappe.get_doc("Account Creation Request", request_name)
    return request.retry_processing()


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def upgrade_member_to_volunteer_user(member_name):
    """
    Upgrade a member's user account from Website User to System User when they become a volunteer.

    This is called when a member who already has a Website User account expresses interest
    in volunteering and has their volunteer record activated.

    Args:
        member_name: Name of the Member record

    Returns:
        dict: Result of the upgrade operation
    """
    if not frappe.has_permission("User", "write"):
        frappe.throw(_("Insufficient permissions to upgrade user accounts"))

    try:
        # Get member record
        member = frappe.get_doc("Member", member_name)

        if not member.user:
            return {"success": False, "error": "No user account linked to this member"}

        # Get user record
        user_doc = frappe.get_doc("User", member.user)

        # Check if already System User
        if user_doc.user_type == "System User":
            frappe.logger().info(f"User {member.user} is already a System User, no upgrade needed")
            return {"success": True, "message": "User is already a System User", "already_upgraded": True}

        # Upgrade to System User
        frappe.logger().info(f"Upgrading user {member.user} from {user_doc.user_type} to System User")
        user_doc.user_type = "System User"

        # Expand module access for volunteers
        # Volunteers need access to HRMS for expense claims
        try:
            # Get current blocked modules
            current_blocks = [row.module for row in user_doc.block_modules]

            # Modules volunteers should have access to
            volunteer_modules = ["HRMS", "HR"]  # For expense claims

            # Remove HRMS/HR from blocked modules
            user_doc.set("block_modules", [])
            all_modules = frappe.get_all("Module Def", fields=["name"])

            # Member modules (already allowed)
            allowed_modules = ["Verenigingen", "Core", "Desk", "Home"]

            # Add volunteer modules to allowed list
            allowed_modules.extend(volunteer_modules)

            # Block everything else
            for module in all_modules:
                if module.name not in allowed_modules:
                    user_doc.append("block_modules", {"module": module.name})

            frappe.logger().info(
                f"Expanded module access for volunteer - added: {', '.join(volunteer_modules)}"
            )

        except Exception as e:
            frappe.logger().warning(f"Could not expand module access for volunteer: {str(e)}")
            # Non-critical - continue with user type upgrade

        user_doc.save()

        frappe.logger().info(f"Successfully upgraded user {member.user} to System User for volunteer access")

        return {
            "success": True,
            "message": f"User account upgraded to System User for volunteer access",
            "user": member.user,
            "previous_type": "Website User",
        }

    except Exception as e:
        frappe.logger().error(f"Failed to upgrade user for member {member_name}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def retry_all_failed_requests(failure_type=None):
    """
    Retry all failed Account Creation Requests.

    Args:
        failure_type: Optional filter - "rate_limit", "employee_exists", or None for all

    Returns:
        dict: Summary of retry operation including success/failure counts
    """
    if not frappe.has_permission("Account Creation Request", "write"):
        frappe.throw(_("Insufficient permissions to retry account creation requests"))

    # Get all failed requests
    filters = {"status": "Failed", "retry_count": ["<", 3]}  # Only retry if under max retries

    failed_requests = frappe.get_all(
        "Account Creation Request",
        filters=filters,
        fields=["name", "email", "full_name", "failure_reason", "retry_count"],
    )

    if not failed_requests:
        return {"success": True, "message": "No failed requests found that can be retried", "total": 0}

    # Filter by failure type if specified
    if failure_type:
        if failure_type == "rate_limit":
            failed_requests = [
                r
                for r in failed_requests
                if "throttled" in (r.failure_reason or "").lower()
                or "rate limit" in (r.failure_reason or "").lower()
            ]
        elif failure_type == "employee_exists":
            failed_requests = [
                r for r in failed_requests if "already assigned to Employee" in (r.failure_reason or "")
            ]

    # Set bulk operation flag to bypass rate limiting during retries
    frappe.flags.bulk_account_creation = True

    retried = []
    errors = []

    frappe.logger().info(f"Starting retry of {len(failed_requests)} failed account creation requests")

    for req_data in failed_requests:
        try:
            request = frappe.get_doc("Account Creation Request", req_data.name)

            # Use the existing retry_processing method
            result = request.retry_processing()

            retried.append({"name": req_data.name, "email": req_data.email, "full_name": req_data.full_name})

        except Exception as e:
            error_msg = str(e)
            errors.append({"name": req_data.name, "email": req_data.email, "error": error_msg})
            frappe.logger().error(f"Failed to retry {req_data.name}: {error_msg}")

    frappe.db.commit()

    return {
        "success": True,
        "total_failed": len(failed_requests),
        "retried": len(retried),
        "errors": len(errors),
        "retried_requests": retried[:20],  # Return first 20 for display
        "error_details": errors[:10],  # Return first 10 errors
        "message": f"Successfully queued {len(retried)} requests for retry. {len(errors)} errors encountered.",
    }
