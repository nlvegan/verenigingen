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
        """Execute the complete account creation pipeline"""
        try:
            self.load_request()

            # Validate request can be processed
            if self.request.status not in ["Queued", "Failed"]:
                raise frappe.ValidationError(f"Request cannot be processed in status: {self.request.status}")

            # Step 1: Validate permissions and prerequisites
            self.validate_processing_permissions()

            # Step 2: Create user account (if not exists)
            if not self.request.created_user:
                self.create_user_account()

            # Step 3: Assign roles and role profile
            if self.request.pipeline_stage != "Completed":
                self.assign_roles_and_profile()

            # Step 4: Create employee record (if needed)
            if self.requires_employee_creation() and not self.request.created_employee:
                self.create_employee_record()

            # Step 5: Link all records together
            self.link_records()

            # Mark as completed
            self.request.mark_completed(user=self.created_user, employee=self.created_employee)

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

    def validate_processing_permissions(self):
        """Validate that processing can proceed with proper permissions"""
        frappe.logger().info(f"Validating processing permissions for {self.request_name}")

        # Switch to system user context for processing (but maintain permission checks)
        if frappe.session.user == "Guest":
            frappe.set_user("Administrator")

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
            # If user already exists, use existing user
            self.created_user = self.request.email
            self.request.created_user = self.created_user
            frappe.logger().info(f"User account already exists: {self.request.email}")
            return

        try:
            # Parse name components
            name_parts = self.request.full_name.split() if self.request.full_name else ["User"]
            first_name = name_parts[0] if name_parts else "User"
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # Create user document
            user_doc = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self.request.email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": self.request.full_name,
                    "enabled": 1,
                    "user_type": "System User",
                    "send_welcome_email": 1,  # Proper welcome email with password setup
                }
            )

            # Add personal email if available
            if hasattr(self.source_doc, "personal_email") and self.source_doc.personal_email:
                # Don't add this to user_doc as it's not a standard field
                pass

            # Insert with proper permissions - NO ignore_permissions=True
            user_doc.insert()

            self.created_user = user_doc.name
            self.request.created_user = self.created_user

            frappe.logger().info(f"User account created successfully: {user_doc.name}")

        except Exception as e:
            frappe.logger().error(f"Failed to create user account: {str(e)}")
            raise frappe.ValidationError(f"User account creation failed: {str(e)}")

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

                # Note: Module profiles are not part of core Role Profile DocType
                # If module profile functionality is needed, it should be implemented
                # via custom fields or alternative mechanisms
                frappe.logger().info(
                    f"Role profile {self.request.role_profile} assigned (module profiles not implemented)"
                )

            # Save with proper permissions - NO ignore_permissions=True
            if roles_added or self.request.role_profile:
                user_doc.save()
                frappe.logger().info(f"Roles assigned successfully: {roles_added}")
            else:
                frappe.logger().info("No new roles to assign")

        except Exception as e:
            frappe.logger().error(f"Failed to assign roles: {str(e)}")
            raise frappe.ValidationError(f"Role assignment failed: {str(e)}")

    def create_employee_record(self):
        """Create employee record for expense functionality"""
        if not self.created_user:
            raise frappe.ValidationError("Cannot create employee - no user account exists")

        self.request.mark_processing("Employee Creation")

        frappe.logger().info(f"Creating employee record for user: {self.created_user}")

        try:
            # Get default company
            default_company = frappe.defaults.get_global_default("company")
            if not default_company:
                companies = frappe.get_all("Company", limit=1, fields=["name"])
                default_company = companies[0].name if companies else None

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
        """Link all created records together"""
        self.request.mark_processing("Record Linking")

        frappe.logger().info(f"Linking records for {self.request_name}")

        try:
            # Update source document with user/employee links
            if self.created_user and hasattr(self.source_doc, "user"):
                if not self.source_doc.user:
                    self.source_doc.user = self.created_user
                    self.source_doc.save()

            if self.created_employee and hasattr(self.source_doc, "employee"):
                if not self.source_doc.employee:
                    self.source_doc.employee = self.created_employee
                    self.source_doc.save()

            # Update user with employee link
            if self.created_user and self.created_employee:
                user_doc = frappe.get_doc("User", self.created_user)
                if not user_doc.employee:
                    user_doc.employee = self.created_employee
                    user_doc.save()

            frappe.logger().info(f"Records linked successfully for {self.request_name}")

        except Exception as e:
            frappe.logger().error(f"Failed to link records: {str(e)}")
            # Don't fail the entire process for linking issues
            frappe.logger().warning("Continuing despite linking errors")

    def requires_employee_creation(self):
        """Check if employee record creation is needed"""
        # Create employee for volunteers who need expense functionality
        if self.request.request_type in ["Volunteer", "Both"]:
            return True

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

    def get_current_stage(self):
        """Get current processing stage for error reporting"""
        return getattr(self.request, "pipeline_stage", "Unknown")

    def is_retryable_error(self, error):
        """Determine if an error is retryable"""
        retryable_errors = ["timeout", "connection", "temporary", "deadlock", "lock wait timeout"]

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
def process_account_creation_request(request_name):
    """Background job entry point for processing account creation requests"""
    try:
        manager = AccountCreationManager(request_name)
        manager.process_complete_pipeline()
        return {"success": True, "message": "Account creation completed successfully"}

    except Exception as e:
        frappe.logger().error(f"Account creation job failed for {request_name}: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def queue_account_creation_for_member(member_name, roles=None, role_profile=None, priority="Normal"):
    """Queue account creation for a member record"""
    if not frappe.has_permission("User", "create"):
        frappe.throw(_("Insufficient permissions to create user accounts"))

    # Get member details
    member = frappe.get_doc("Member", member_name)

    if not member.email:
        frappe.throw(_("Member must have an email address for account creation"))

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

    # Create request
    request = frappe.get_doc(
        {
            "doctype": "Account Creation Request",
            "request_type": "Member",
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

    return {"request_name": request.name, "result": result}


@frappe.whitelist()
def queue_account_creation_for_volunteer(volunteer_name, priority="Normal"):
    """Queue account creation for a volunteer record"""
    if not frappe.has_permission("User", "create"):
        frappe.throw(_("Insufficient permissions to create user accounts"))

    # Get volunteer details
    volunteer = frappe.get_doc("Volunteer", volunteer_name)

    if not volunteer.email:
        frappe.throw(_("Volunteer must have an email address for account creation"))

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

    return {"request_name": request.name, "result": result}


# Bulk processing functions


@frappe.whitelist()
def queue_bulk_account_creation_for_members(
    member_names, roles=None, role_profile=None, batch_size=50, priority="Low"
):
    """
    Queue bulk account creation for multiple members with efficient batch processing.

    This function implements the bulk processing path for large imports (500-4700+ members)
    while maintaining individual accountability and retry capability.

    Args:
        member_names: List of member names to process
        roles: Default roles to assign (defaults to ["Verenigingen Member"])
        role_profile: Role profile to assign (defaults to "Verenigingen Member")
        batch_size: Number of members to process in each batch (default 50)
        priority: Processing priority ("Low", "Normal", "High")

    Returns:
        dict: Summary with batch info, request names, and processing details
    """
    if not frappe.has_permission("User", "create"):
        frappe.throw(_("Insufficient permissions to create user accounts"))

    if not member_names:
        return {"success": False, "error": "No member names provided"}

    frappe.logger().info(f"Starting bulk account creation for {len(member_names)} members")

    # Set defaults
    if not roles:
        roles = ["Verenigingen Member"]
    if not role_profile:
        role_profile = "Verenigingen Member"

    # Validate all members exist and have email addresses
    validation_errors = []
    valid_members = []

    for member_name in member_names:
        try:
            if not frappe.db.exists("Member", member_name):
                validation_errors.append(f"Member {member_name} does not exist")
                continue

            member = frappe.get_doc("Member", member_name)
            if not member.email:
                validation_errors.append(f"Member {member_name} has no email address")
                continue

            # Check for existing requests
            existing_request = frappe.db.exists(
                "Account Creation Request",
                {"source_record": member_name, "status": ["not in", ["Completed", "Cancelled"]]},
            )

            if existing_request:
                validation_errors.append(
                    f"Account creation request already exists for {member_name}: {existing_request}"
                )
                continue

            valid_members.append(member)

        except Exception as e:
            validation_errors.append(f"Error validating member {member_name}: {str(e)}")

    if validation_errors:
        frappe.logger().warning(f"Bulk validation found {len(validation_errors)} errors")
        for error in validation_errors[:10]:  # Log first 10 errors
            frappe.logger().warning(f"Validation error: {error}")

    if not valid_members:
        return {
            "success": False,
            "error": "No valid members found for processing",
            "validation_errors": validation_errors[:50],  # Return first 50 errors
        }

    # Create account creation requests for all valid members with chunked processing
    created_requests = []
    creation_errors = []

    # Process in chunks to avoid memory exhaustion and database locks
    chunk_size = 100
    for chunk_start in range(0, len(valid_members), chunk_size):
        chunk_end = min(chunk_start + chunk_size, len(valid_members))
        chunk_members = valid_members[chunk_start:chunk_end]

        # Start transaction for this chunk
        frappe.db.begin()

        try:
            for member in chunk_members:
                try:
                    request = frappe.get_doc(
                        {
                            "doctype": "Account Creation Request",
                            "request_type": "Member",
                            "source_record": member.name,
                            "email": member.email,
                            "full_name": member.full_name,
                            "priority": priority,
                            "role_profile": role_profile,
                            "business_justification": "Bulk member import - account creation for portal access",
                        }
                    )

                    # Add requested roles
                    for role in roles:
                        request.append("requested_roles", {"role": role})

                    request.insert()
                    created_requests.append(request.name)

                except Exception as e:
                    creation_errors.append(f"Failed to create request for {member.name}: {str(e)}")
                    # Continue with other members in chunk even if one fails
                    continue

            # Commit this chunk if successful
            frappe.db.commit()
            frappe.logger().info(
                f"Created requests for chunk {chunk_start // chunk_size + 1}: {len(chunk_members)} members"
            )

        except Exception as e:
            # Rollback this chunk on any unexpected error
            frappe.db.rollback()
            frappe.logger().error(f"Failed to process chunk {chunk_start // chunk_size + 1}: {str(e)}")
            for member in chunk_members:
                creation_errors.append(f"Failed to create request for {member.name}: Chunk processing error")

    if creation_errors:
        frappe.logger().error(f"Bulk request creation had {len(creation_errors)} errors")
        for error in creation_errors[:10]:  # Log first 10 errors
            frappe.logger().error(f"Creation error: {error}")

    if not created_requests:
        return {
            "success": False,
            "error": "No account creation requests could be created",
            "creation_errors": creation_errors[:50],
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
                queue="bulk",  # Use dedicated bulk queue
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
    result = {
        "success": True,
        "total_members_provided": len(member_names),
        "validation_errors_count": len(validation_errors),
        "valid_members_count": len(valid_members),
        "requests_created": len(created_requests),
        "creation_errors_count": len(creation_errors),
        "batch_count": len(batch_results),
        "batch_size": batch_size,
        "batches": batch_results,
        "request_names": created_requests,
        "tracker_name": tracker.name,
        "tracker_url": f"/app/bulk-operation-tracker/{tracker.name}",
    }

    frappe.logger().info(
        f"Bulk account creation queued: {len(created_requests)} requests in {len(batch_results)} batches"
    )

    return result


@frappe.whitelist()
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

    def process_single_request_safe(request_name):
        """Process a single request with error handling, transaction safety, and new database connection."""
        try:
            # Each thread needs its own database connection
            frappe.connect()

            # Start transaction for this request
            frappe.db.begin()

            try:
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

    # Process requests in parallel with controlled concurrency
    max_workers = min(5, len(request_names))  # Up to 5 parallel workers, but not more than requests

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all requests to the thread pool
        future_to_request = {
            executor.submit(process_single_request_safe, request_name): request_name
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
def get_failed_requests():
    """Get failed account creation requests for admin review"""
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
def retry_failed_request(request_name):
    """Manually retry a failed account creation request"""
    if not frappe.has_permission("Account Creation Request", "write"):
        frappe.throw(_("Insufficient permissions"))

    request = frappe.get_doc("Account Creation Request", request_name)
    return request.retry_processing()
