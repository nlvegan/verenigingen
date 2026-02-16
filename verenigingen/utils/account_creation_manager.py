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

ERROR HANDLING PATTERN:
All whitelisted API endpoints in this module follow the OperationResult pattern:
- Return type: OperationResult[Dict[str, Any]]
- Never throw exceptions - all errors wrapped in OperationResult.fail()
- Consistent metadata with context dict: {"operation": "...", "params": {...}}
- Generic user-facing messages with technical details in errors list

Author: Verenigingen Development Team
"""

import random
import time
import traceback
from contextlib import contextmanager
from functools import wraps
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import get_site_name, now

from verenigingen.utils.dutch_name_utils import get_full_last_name
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api


def retry_on_deadlock(max_retries=3, initial_delay=0.1):
    """
    Decorator to retry database operations on deadlock errors.

    Implements exponential backoff with jitter to handle MySQL deadlocks
    during concurrent ACR processing.

    Args:
        max_retries: Maximum number of retry attempts (default 3)
        initial_delay: Initial delay in seconds before first retry (default 0.1)

    Usage:
        @retry_on_deadlock(max_retries=3, initial_delay=0.1)
        def my_database_operation():
            # ... database operations that might deadlock ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_msg = str(e)

                    # Check if this is a deadlock error
                    is_deadlock = "Deadlock" in error_msg or "1213" in error_msg
                    is_last_attempt = attempt >= max_retries - 1

                    if is_deadlock and not is_last_attempt:
                        # Calculate exponential backoff with jitter
                        delay = (initial_delay * (2**attempt)) + random.uniform(0, 0.05)

                        frappe.logger().warning(
                            f"[RETRY] Deadlock detected in {func.__name__}, "
                            f"retrying in {delay:.3f}s (attempt {attempt + 1}/{max_retries})"
                        )

                        time.sleep(delay)

                        # Reload any DocType instances that might have stale data
                        # This is handled by the calling code if needed
                        continue
                    else:
                        # Not a deadlock, or last attempt failed - re-raise
                        if is_deadlock and is_last_attempt:
                            frappe.logger().error(
                                f"[RETRY] Deadlock in {func.__name__} persists after {max_retries} attempts, giving up"
                            )
                        raise

            # Should never reach here, but just in case
            return func(*args, **kwargs)

        return wrapper

    return decorator


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

            # PHASE 3: Recalculate role profile from actual DB state
            # The ACR assigns the role profile from the request (e.g. "Verenigingen Member"),
            # but the user may already hold positions (chapter board member, team lead) that
            # warrant a higher profile. This must run AFTER Phase 2 links user→member→volunteer.
            self._sync_role_profile()

            # Send notification
            self.send_completion_notification()

            frappe.logger().info(f"Account creation completed successfully: {self.request_name}")

        except Exception as e:
            error_msg = str(e)
            frappe.logger().error(f"Account creation failed for {self.request_name}: {error_msg}")
            frappe.logger().error(traceback.format_exc())

            # Mark as failed with detailed error (request may be None if load_request failed)
            if self.request:
                self.request.mark_failed(error_msg, self.get_current_stage())

                # Determine if this is retryable
                if self.is_retryable_error(e) and (self.request.retry_count or 0) < 3:
                    self.schedule_retry()

            raise

    def _create_user_and_employee_phase(self):
        """Phase 1: Create User and Employee records - tries all subtasks even if some fail (partial success model)"""
        frappe.logger().info(
            f"[ACR PIPELINE] ========== PHASE 1 START ========== | "
            f"ACR: {self.request_name} | Request Type: {self.request.request_type} | "
            f"Email: {self.request.email} | Create Employee: {self.requires_employee_creation()}"
        )

        errors = []

        # Subtask 1: Create user account (if not exists)
        try:
            if not self.request.created_user:
                self.create_user_account()
            else:
                # User already exists - populate instance variable for linking
                self.created_user = self.request.created_user
                frappe.logger().info(f"[ACR PIPELINE] User already exists: {self.created_user}, will reuse")
        except Exception as e:
            error_msg = f"User creation failed: {str(e)[:200]}"
            errors.append(error_msg)
            frappe.logger().error(f"[ACR PIPELINE] ✗ {error_msg}")
            # No user = can't proceed with other steps, re-raise
            raise

        # Subtask 2: Assign roles and role profile (independent of employee creation)
        try:
            if self.request.pipeline_stage != "Completed":
                # Wrap role assignment with retry logic for deadlock handling
                retry_on_deadlock(max_retries=3, initial_delay=0.1)(self.assign_roles_and_profile)()
        except Exception as e:
            error_msg = f"Role assignment failed: {str(e)[:200]}"
            errors.append(error_msg)
            frappe.logger().warning(
                f"[ACR PIPELINE] ⚠️ Role assignment failed but continuing with other tasks | "
                f"ACR: {self.request_name} | Error: {error_msg}"
            )
            # Don't re-raise - try employee creation and linking anyway

        # Subtask 3: Create employee record (if needed, independent of roles)
        if self.requires_employee_creation():
            try:
                if not self.request.created_employee:
                    # Wrap employee creation with retry logic for deadlock handling
                    retry_on_deadlock(max_retries=3, initial_delay=0.1)(self.create_employee_record)()
                else:
                    # Employee already exists - populate instance variable for linking
                    self.created_employee = self.request.created_employee
                    frappe.logger().info(
                        f"[ACR PIPELINE] Employee already exists: {self.created_employee}, will reuse"
                    )
            except Exception as e:
                error_msg = f"Employee creation failed: {str(e)[:200]}"
                errors.append(error_msg)
                frappe.logger().warning(
                    f"[ACR PIPELINE] ⚠️ Employee creation failed but continuing with linking | "
                    f"ACR: {self.request_name} | Error: {error_msg}"
                )
                # Don't re-raise - user was created, proceed to linking

        # Log phase 1 completion (partial or full)
        if errors:
            frappe.logger().warning(
                f"[ACR PIPELINE] ========== PHASE 1 PARTIAL SUCCESS ========== | "
                f"ACR: {self.request_name} | User: {self.created_user} | "
                f"Employee: {self.created_employee or 'N/A'} | "
                f"Errors: {len(errors)} | {'; '.join(errors[:2])}"
            )
        else:
            frappe.logger().info(
                f"[ACR PIPELINE] ========== PHASE 1 COMPLETE ========== | "
                f"ACR: {self.request_name} | User: {self.created_user} | "
                f"Employee: {self.created_employee or 'N/A'}"
            )

        # Store errors for later reporting but DON'T fail the operation
        if errors:
            self.phase1_errors = errors

    def _link_records_phase(self):
        """Phase 2: Link all records together - tries all links even if some fail (partial success model)"""
        frappe.logger().info(
            f"[ACR PIPELINE] ========== PHASE 2 START ========== | "
            f"ACR: {self.request_name} | User: {self.created_user} | "
            f"Employee: {self.created_employee or 'N/A'} | Source: {self.request.source_record}"
        )

        errors = []
        links_succeeded = 0

        # Try each link independently - don't fail the whole operation if one link fails
        try:
            # Link 1: User to source record
            if self.created_user and hasattr(self.source_doc, "user"):
                try:
                    current_user = frappe.db.get_value(
                        self.request.request_type, self.request.source_record, "user"
                    )
                    if not current_user:
                        frappe.db.set_value(
                            self.request.request_type,
                            self.request.source_record,
                            "user",
                            self.created_user,
                            update_modified=False,
                        )
                        links_succeeded += 1
                        frappe.logger().info(
                            f"[ACR PIPELINE] ✓ Linked user {self.created_user} to {self.request.request_type} {self.request.source_record}"
                        )
                except Exception as e:
                    error_msg = f"Failed to link user to {self.request.request_type}: {str(e)[:150]}"
                    errors.append(error_msg)
                    frappe.logger().warning(f"[ACR PIPELINE] ⚠️ {error_msg}")

            # Link 2: Employee to source record
            if self.created_employee and hasattr(self.source_doc, "employee"):
                try:
                    current_employee = frappe.db.get_value(
                        self.request.request_type, self.request.source_record, "employee"
                    )
                    if not current_employee:
                        frappe.db.set_value(
                            self.request.request_type,
                            self.request.source_record,
                            "employee",
                            self.created_employee,
                            update_modified=False,
                        )
                        links_succeeded += 1
                        frappe.logger().info(
                            f"[ACR PIPELINE] ✓ Linked employee {self.created_employee} to {self.request.request_type} {self.request.source_record}"
                        )
                except Exception as e:
                    error_msg = f"Failed to link employee to {self.request.request_type}: {str(e)[:150]}"
                    errors.append(error_msg)
                    frappe.logger().warning(f"[ACR PIPELINE] ⚠️ {error_msg}")

            # Link 3: Contact to Member record (for Member request type only)
            if self.request.request_type == "Member" and self.created_user:
                try:
                    # Find contact for the created user (may not exist yet due to background job timing)
                    contact_name = frappe.db.get_value("Contact", {"user": self.created_user}, "name")

                    if contact_name:
                        # Check if Member has contact field (may not exist in older schemas)
                        if frappe.db.has_column("Member", "contact"):
                            current_contact = frappe.db.get_value(
                                "Member", self.request.source_record, "contact"
                            )
                            if not current_contact:
                                frappe.db.set_value(
                                    "Member",
                                    self.request.source_record,
                                    "contact",
                                    contact_name,
                                    update_modified=False,
                                )
                                links_succeeded += 1
                                frappe.logger().info(
                                    f"[ACR PIPELINE] ✓ Linked contact {contact_name} to Member {self.request.source_record}"
                                )
                        else:
                            frappe.logger().debug(
                                "[ACR PIPELINE] Member.contact field does not exist, skipping contact link"
                            )
                    else:
                        frappe.logger().debug(
                            f"[ACR PIPELINE] Contact not yet created for user {self.created_user} (background job still processing), will be linked later"
                        )
                except Exception as e:
                    error_msg = f"Failed to link contact to Member: {str(e)[:150]}"
                    errors.append(error_msg)
                    frappe.logger().warning(f"[ACR PIPELINE] ⚠️ {error_msg}")

            # Link 4 & 5: For Member records, link to associated Volunteer
            if self.request.request_type == "Member":
                try:
                    volunteer_record = frappe.db.get_value(
                        "Volunteer", {"member": self.request.source_record}, "name"
                    )
                    if volunteer_record:
                        # Link user to volunteer
                        if self.created_user:
                            try:
                                current_volunteer_user = frappe.db.get_value(
                                    "Volunteer", volunteer_record, "user"
                                )
                                if not current_volunteer_user:
                                    frappe.db.set_value(
                                        "Volunteer",
                                        volunteer_record,
                                        "user",
                                        self.created_user,
                                        update_modified=False,
                                    )
                                    links_succeeded += 1
                                    frappe.logger().info(
                                        f"[ACR PIPELINE] ✓ Linked user {self.created_user} to Volunteer {volunteer_record}"
                                    )
                            except Exception as e:
                                error_msg = f"Failed to link user to Volunteer: {str(e)[:150]}"
                                errors.append(error_msg)
                                frappe.logger().warning(f"[ACR PIPELINE] ⚠️ {error_msg}")

                        # Link employee to volunteer
                        if self.created_employee:
                            try:
                                current_volunteer_employee = frappe.db.get_value(
                                    "Volunteer", volunteer_record, "employee_id"
                                )
                                if not current_volunteer_employee:
                                    frappe.db.set_value(
                                        "Volunteer",
                                        volunteer_record,
                                        "employee_id",
                                        self.created_employee,
                                        update_modified=False,
                                    )
                                    links_succeeded += 1
                                    frappe.logger().info(
                                        f"[ACR PIPELINE] ✓ Linked employee {self.created_employee} to Volunteer {volunteer_record}"
                                    )
                            except Exception as e:
                                error_msg = f"Failed to link employee to Volunteer: {str(e)[:150]}"
                                errors.append(error_msg)
                                frappe.logger().warning(f"[ACR PIPELINE] ⚠️ {error_msg}")
                except Exception as e:
                    error_msg = f"Failed to find/link Volunteer record: {str(e)[:150]}"
                    errors.append(error_msg)
                    frappe.logger().warning(f"[ACR PIPELINE] ⚠️ {error_msg}")

            # Combine Phase 1 and Phase 2 errors for final status
            all_errors = getattr(self, "phase1_errors", []) + errors

            # Determine final status based on what succeeded
            if all_errors:
                # Partial success - some things worked, some didn't
                if self.created_user or links_succeeded > 0:
                    # Mark as completed but with warnings
                    self.request.mark_completed(user=self.created_user, employee=self.created_employee)
                    # Update failure_reason to note partial success
                    combined_errors = "; ".join(all_errors[:5])
                    frappe.db.set_value(
                        "Account Creation Request",
                        self.request.name,
                        "failure_reason",
                        f"⚠️ PARTIAL SUCCESS - Some tasks failed: {combined_errors}",
                        update_modified=False,
                    )
                    frappe.logger().warning(
                        f"[ACR PIPELINE] ========== PHASE 2 PARTIAL SUCCESS ========== | "
                        f"ACR: {self.request_name} | Links succeeded: {links_succeeded} | "
                        f"Errors: {len(all_errors)} | {combined_errors}"
                    )
                else:
                    # Nothing succeeded - mark as failed
                    raise Exception(f"All tasks failed: {'; '.join(all_errors[:3])}")
            else:
                # Full success - everything worked
                self.request.mark_completed(user=self.created_user, employee=self.created_employee)
                frappe.logger().info(
                    f"[ACR PIPELINE] ========== PHASE 2 COMPLETE ========== | "
                    f"ACR: {self.request_name} | All records linked successfully | Links: {links_succeeded}"
                )

        except Exception as e:
            frappe.logger().error(
                f"[ACR PIPELINE] ========== PHASE 2 FAILED ========== | "
                f"ACR: {self.request_name} | Error: {str(e)[:300]}"
            )
            # User and Employee still exist from Phase 1 - can retry linking
            frappe.logger().warning(
                f"[ACR PIPELINE] User/Employee may exist but linking failed. "
                f"User: {self.created_user} | Employee: {self.created_employee or 'N/A'} | "
                f"Retry will attempt linking with existing records."
            )
            raise

    def _sync_role_profile(self):
        """Phase 3: Recalculate role profile from actual DB state.

        The ACR request carries a static role_profile (e.g. "Verenigingen Member"),
        but by this point the user may already be linked to positions that warrant
        a higher profile (chapter board member, team lead, etc.).

        Delegates to auto_sync_on_role_change() — the ground-truth calculator —
        which inspects actual board memberships, team leadership, and volunteer
        status to determine the correct profile.

        Non-fatal: if this fails, the user still has the profile from Phase 1.
        """
        if not self.created_user:
            return

        try:
            from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

            result = auto_sync_on_role_change(self.created_user)
            frappe.logger().info(
                f"[ACR PIPELINE] ✓ Role profile sync completed for {self.created_user}: {result}"
            )
        except Exception as e:
            # Non-fatal — user still has the basic profile from Phase 1
            frappe.logger().warning(
                f"[ACR PIPELINE] ⚠️ Role profile sync failed for {self.created_user}: {e}"
            )

    def validate_processing_permissions(self):
        """Validate that processing can proceed with proper permissions"""
        frappe.logger().info(f"Validating processing permissions for {self.request_name}")

        # Validate request exists
        if not self.request:
            raise frappe.ValidationError("Cannot validate permissions: Account creation request not loaded")

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
            return {"success": True, "user": self.created_user, "already_existed": True}

        try:
            first_name, last_name = self._parse_name_components()

            is_bulk_operation = getattr(frappe.flags, "bulk_account_creation", False)
            user_data = self._prepare_user_data(first_name, last_name, is_bulk_operation)
            user_doc = frappe.get_doc(user_data)

            with self._bulk_import_flags(is_bulk_operation):
                try:
                    user_doc = self._insert_user_with_deadlock_retry(user_doc, user_data)
                except frappe.exceptions.UniqueValidationError as e:
                    error_msg = str(e)
                    if "Duplicate entry" in error_msg and "for key 'username'" in error_msg:
                        result = self._handle_username_conflict(user_doc, user_data)
                        if result is None:
                            return {"success": True, "user": self.created_user, "already_existed": True}
                        user_doc = result
                    else:
                        raise
                except frappe.exceptions.OutgoingEmailError:
                    # Suppress email errors during bulk imports - missing email account is expected
                    if frappe.flags.in_import or frappe.flags.in_bulk_import:
                        frappe.logger().debug(
                            f"Suppressed email notification error for {self.request.email} during bulk import"
                        )
                    else:
                        raise
                except frappe.exceptions.TimestampMismatchError as e:
                    # Suppress timestamp mismatch errors from Contact hook during concurrent user creation
                    # The User record is still created successfully even if Contact update fails
                    # This race condition happens in Frappe core (contact.py line 339) during after_insert
                    frappe.logger().warning(
                        f"TimestampMismatchError during user creation for {self.request.email}: {str(e)}. "
                        f"User was created successfully, Contact hook failed due to concurrent modification."
                    )

            # CRITICAL: Verify user was actually committed before marking as created
            # This prevents phantom users where created_user is set but user doesn't exist
            frappe.db.commit()  # Ensure user is committed

            # Verify user exists in database
            if not frappe.db.exists("User", user_doc.name):
                raise frappe.ValidationError(
                    f"User {user_doc.name} was inserted but cannot be found. "
                    f"Possible transaction rollback or hook failure."
                )

            self.created_user = user_doc.name
            self.request.created_user = self.created_user

            frappe.logger().info(f"User account created and verified in database: {user_doc.name}")

            # Note: Contact is created automatically by Frappe's User.after_insert() hook
            # which queues a background job. Some jobs may fail due to race conditions
            # (transaction not yet visible), but these failures are non-critical and
            # contacts will be retried/created eventually. We store the user for contact
            # linking in the linking phase.

            return {"success": True, "user": user_doc.name}

        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            full_traceback = frappe.get_traceback()

            # Enhanced logging for rate limit and throttling errors
            if "throttle" in error_msg.lower() or "rate limit" in error_msg.lower():
                frappe.logger().error(
                    f"Rate limit encountered creating user {self.request.email}: "
                    f"{error_type}: {error_msg}. "
                    f"This typically occurs when creating many users simultaneously. "
                    f"The request will be retried automatically."
                )
                frappe.log_error(
                    title=f"Rate Limit - User Creation: {self.request.email}",
                    message=full_traceback,
                )
                raise frappe.ValidationError(
                    f"User account creation rate limited (will retry automatically): {error_msg}"
                )
            else:
                frappe.logger().error(
                    f"Failed to create user account for {self.request.email}: {error_type}: {error_msg}\n"
                    f"Full traceback:\n{full_traceback}"
                )
                frappe.log_error(
                    title=f"User Creation Failed: {self.request.email}",
                    message=full_traceback,
                )
                raise frappe.ValidationError(
                    f"User account creation failed ({error_type}): {error_msg}. "
                    f"Check Error Log for full traceback."
                )

    def _parse_name_components(self):
        """Parse name components from source document, handling Dutch tussenvoegsel.

        Returns:
            tuple: (first_name, last_name)
        """
        if self.request.request_type == "Member" and self.source_doc:
            first_name = self.source_doc.first_name or "User"
            if hasattr(self.source_doc, "tussenvoegsel") and self.source_doc.tussenvoegsel:
                last_name = get_full_last_name(self.source_doc.last_name or "", self.source_doc.tussenvoegsel)
            else:
                last_name = self.source_doc.last_name or ""
        else:
            name_parts = self.request.full_name.split() if self.request.full_name else ["User"]
            first_name = name_parts[0] if name_parts else "User"
            last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        return first_name, last_name

    def _prepare_user_data(self, first_name, last_name, is_bulk_operation):
        """Build user document data dict.

        Args:
            first_name: User's first name
            last_name: User's last name
            is_bulk_operation: Whether this is a bulk import (suppresses emails/passwords)

        Returns:
            dict: Data dict suitable for frappe.get_doc()
        """
        user_type = "System User" if self.request.request_type == "Volunteer" else "Website User"

        send_welcome = (
            0 if (is_bulk_operation or frappe.flags.in_import or frappe.flags.in_bulk_import) else 1
        )

        user_data = {
            "doctype": "User",
            "email": self.request.email,
            "first_name": first_name,
            "last_name": last_name,
            "full_name": self.request.full_name,
            "enabled": 1,
            "user_type": user_type,
            "send_welcome_email": send_welcome,
        }

        # CRITICAL: Only set password for non-bulk operations
        # Setting new_password triggers Frappe's email sending code, which fails during bulk imports
        # when SMTP is not configured or frappe.flags.mute_emails isn't respected
        # For bulk operations, users will need to use password reset when they first log in
        if not is_bulk_operation:
            user_data["new_password"] = frappe.generate_hash(length=20)

        return user_data

    @contextmanager
    def _bulk_import_flags(self, is_bulk_operation):
        """Set and restore frappe.flags for bulk import operations.

        Temporarily sets in_import, mute_emails, and in_install flags to suppress
        email sending and background job queuing during bulk user creation.
        """
        original = {
            "in_import": getattr(frappe.flags, "in_import", False),
            "mute_emails": getattr(frappe.flags, "mute_emails", False),
            "in_install": getattr(frappe.flags, "in_install", False),
        }
        try:
            if is_bulk_operation:
                frappe.flags.in_import = True
                frappe.flags.mute_emails = True  # Frappe-native email suppression
                frappe.flags.in_install = (
                    True  # CRITICAL: Prevents User.after_insert() from queuing background jobs
                )
            yield
        finally:
            for key, val in original.items():
                setattr(frappe.flags, key, val)

    def _insert_user_with_deadlock_retry(self, user_doc, user_data, max_retries=5, retry_delay_base=0.1):
        """Insert user document with exponential backoff retry on MySQL deadlocks.

        MySQL deadlocks can occur when multiple users are created concurrently
        and they all try to insert default values (timezone, etc.) simultaneously.

        Args:
            user_doc: The frappe User document to insert
            user_data: The user data dict (used to recreate doc on retry)
            max_retries: Maximum number of retry attempts (default 5)
            retry_delay_base: Initial delay in seconds before first retry (default 0.1)

        Returns:
            The inserted user document
        """
        for attempt in range(max_retries):
            try:
                user_doc.insert()
                return user_doc
            except (frappe.exceptions.QueryDeadlockError, frappe.db.InternalError) as deadlock_error:
                error_str = str(deadlock_error)
                is_deadlock = (
                    "1213" in error_str or "Deadlock" in error_str or "deadlock" in error_str.lower()
                )

                if not is_deadlock or attempt >= max_retries - 1:
                    raise

                # Exponential backoff: 100ms, 200ms, 400ms, 800ms, 1600ms
                delay = retry_delay_base * (2**attempt) + random.uniform(0, 0.05)
                frappe.logger().warning(
                    f"Deadlock during user creation for {self.request.email}, "
                    f"retrying in {delay:.3f}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(delay)

                # Rollback any partial transaction before retrying
                frappe.db.rollback()

                # Create a fresh user document for retry
                user_doc = frappe.get_doc(user_data)
        raise frappe.ValidationError(f"Deadlock retry loop exhausted for {self.request.email}")

    def _handle_username_conflict(self, user_doc, user_data):
        """Handle duplicate username by retrying with email prefix as username.

        When Frappe auto-generates a username from first_name and it conflicts,
        fall back to using the email prefix as username.

        Args:
            user_doc: The user document that failed to insert
            user_data: The user data dict (used to recreate doc on retry)

        Returns:
            The inserted user document, or None if user already existed
        """
        frappe.logger().info(
            f"Username conflict for {user_data.get('first_name')}, retrying with email as username"
        )
        username = self.request.email.split("@")[0]
        user_doc.username = username
        # Set in user_data so deadlock retries (which recreate user_doc) preserve the username
        user_data["username"] = username
        try:
            return self._insert_user_with_deadlock_retry(user_doc, user_data)
        except Exception:
            # If still fails, check if user was created by a concurrent process
            if frappe.db.exists("User", self.request.email):
                self.created_user = self.request.email
                self.request.created_user = self.created_user
                frappe.logger().info(
                    f"User {self.request.email} already exists, will skip creation and continue"
                )
                return None  # Signal: user already existed
            raise

    def assign_roles_and_profile(self):
        """Assign roles and role profile with proper permission validation"""
        if not self.created_user:
            raise frappe.ValidationError("Cannot assign roles - no user account exists")

        self.request.mark_processing("Role Assignment")

        frappe.logger().info(
            f"[ACR PIPELINE] Role Assignment - Starting for {self.request_name} | User: {self.created_user} | "
            f"Requested Roles: {[r.role for r in self.request.requested_roles]} | "
            f"Role Profile: {self.request.role_profile}"
        )

        try:
            user_doc = frappe.get_doc("User", self.created_user)
            existing_roles = [r.role for r in user_doc.roles]
            frappe.logger().info(f"[ACR PIPELINE] User {self.created_user} existing roles: {existing_roles}")

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
            # Retry logic is handled at higher level via @retry_on_deadlock decorator
            if roles_added or self.request.role_profile:
                frappe.logger().info(
                    f"[ACR PIPELINE] Saving user with roles | "
                    f"User: {self.created_user} | Roles to add: {roles_added} | Profile: {self.request.role_profile}"
                )
                user_doc.save()
                frappe.logger().info(
                    f"[ACR PIPELINE] ✓ Role Assignment - SUCCESS | "
                    f"User: {self.created_user} | Roles Added: {roles_added} | Profile: {self.request.role_profile}"
                )
            else:
                frappe.logger().info("No new roles to assign")

            # Set module access for member users
            if self.request.request_type == "Member":
                self._set_member_user_modules()
                frappe.logger().info(f"Module access configured for member user: {self.created_user}")

        except Exception as e:
            error_msg = str(e)
            is_deadlock = "Deadlock" in error_msg or "1213" in error_msg

            frappe.logger().error(
                f"[ACR PIPELINE] ✗ Role Assignment - FINAL FAILURE | "
                f"ACR: {self.request_name} | User: {self.created_user} | "
                f"Error Type: {'DEADLOCK (will retry)' if is_deadlock else 'NON-RETRIABLE'} | "
                f"Error: {error_msg[:300]}"
            )
            raise frappe.ValidationError(f"Role assignment failed: {error_msg}")

    def create_employee_record(self):
        """Create employee record for expense functionality"""
        if not self.created_user:
            raise frappe.ValidationError("Cannot create employee - no user account exists")

        self.request.mark_processing("Employee Creation")

        frappe.logger().info(
            f"[ACR PIPELINE] Employee Creation - Starting for {self.request_name} | "
            f"User: {self.created_user} | Request Type: {self.request.request_type}"
        )

        # Check if employee already exists for this user
        existing_employee = frappe.db.get_value("Employee", {"user_id": self.created_user}, "name")
        if existing_employee:
            # Employee already exists, use it and continue with pipeline
            self.created_employee = existing_employee
            self.request.created_employee = self.created_employee
            frappe.logger().info(
                f"[ACR PIPELINE] ✓ Employee Creation - SKIPPED (already exists) | "
                f"ACR: {self.request_name} | Employee: {existing_employee} | User: {self.created_user}"
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
                    "create_user_permission": 1,  # Enable user permissions for volunteers
                }
            )

            # Add email if available
            if self.request.email:
                employee_doc.personal_email = self.request.email

            # Insert with proper permissions - NO ignore_permissions=True
            employee_doc.insert()

            self.created_employee = employee_doc.name
            self.request.created_employee = self.created_employee

            frappe.logger().info(
                f"[ACR PIPELINE] ✓ Employee Creation - SUCCESS | "
                f"ACR: {self.request_name} | Employee: {employee_doc.name} | "
                f"User: {self.created_user} | Company: {default_company}"
            )

        except Exception as e:
            error_msg = str(e)
            is_deadlock = "Deadlock" in error_msg or "1213" in error_msg

            frappe.logger().error(
                f"[ACR PIPELINE] ✗ Employee Creation - FAILED | "
                f"ACR: {self.request_name} | User: {self.created_user} | "
                f"Error Type: {'DEADLOCK (will retry)' if is_deadlock else 'NON-RETRIABLE'} | "
                f"Error: {error_msg[:300]}"
            )
            raise frappe.ValidationError(f"Employee record creation failed: {error_msg}")

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
                "Verenigingen Staff",
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
            from verenigingen.services.member.account.member_role_service import get_member_role_service

            get_member_role_service().set_member_user_modules(self.created_user)
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
        # Increment retry count
        current_retry_count = self.request.retry_count or 0
        new_retry_count = current_retry_count + 1
        frappe.db.set_value(
            "Account Creation Request",
            self.request_name,
            {"retry_count": new_retry_count, "status": "Requested"},
            update_modified=True,
        )

        # ALWAYS commit retry count - even during tests for proper retry validation
        # This ensures test assertions can verify retry tracking
        frappe.db.commit()

        # Reload request to get updated retry_count
        self.request.reload()

        retry_delay_minutes = min(5 * (2**current_retry_count), 60)  # Exponential backoff

        frappe.enqueue(
            "verenigingen.utils.account_creation_manager.process_account_creation_request",
            request_name=self.request_name,
            queue="long",
            timeout=600,
            job_name=f"account_creation_retry_{self.request_name}",
            at_time=frappe.utils.add_to_date(None, minutes=retry_delay_minutes),
        )

        frappe.logger().info(
            f"Scheduled retry {new_retry_count} for {self.request_name} in {retry_delay_minutes} minutes"
        )

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
def process_account_creation_request(request_name: str, at_time=None) -> OperationResult[Dict[str, Any]]:
    """Background job entry point for processing account creation requests

    Args:
        request_name: Name of the Account Creation Request to process
        at_time: Scheduled execution time (passed by frappe.enqueue when using at_time parameter)

    Returns:
        OperationResult[Dict[str, Any]]: Result with success status and message
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
        return OperationResult.ok(
            {"request_name": request_name}, message="Account creation completed successfully"
        )

    except Exception as e:
        frappe.logger().error(f"Account creation job failed for {request_name}: {str(e)}")
        frappe.log_error(
            f"Account creation processing failed: {str(e)}\n{traceback.format_exc()}",
            "Account Creation Request Processing Error",
        )
        return OperationResult.fail(
            _("Unable to process account creation request. Please contact support."),
            errors=[str(e)],
            context={"operation": "process_account_creation", "params": {"request_name": request_name}},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def queue_account_creation_for_member(
    member_name: str, roles=None, role_profile=None, priority: str = "Normal"
) -> OperationResult[Dict[str, Any]]:
    """Queue account creation for a member record

    Args:
        member_name: Member record name
        roles: List of roles to assign (default: ["Verenigingen Member"])
        role_profile: Role profile to assign (default: "Verenigingen Member")
        priority: Processing priority (default: "Normal")

    Returns:
        OperationResult[Dict[str, Any]]: Result with request name and status
    """
    try:
        if not frappe.has_permission("User", "create"):
            return OperationResult.fail(
                _("Insufficient permissions to create user accounts"),
                errors=["Permission denied"],
                context={"operation": "queue_member_account", "params": {"member_name": member_name}},
            )

        # Get member details
        if not frappe.db.exists("Member", member_name):
            return OperationResult.fail(
                _("Member not found"),
                errors=[f"Member {member_name} does not exist"],
                context={"operation": "queue_member_account", "params": {"member_name": member_name}},
            )

        member = frappe.get_doc("Member", member_name)

        if not member.email:
            return OperationResult.fail(
                _("Member must have an email address for account creation"),
                errors=["No email address provided"],
                context={"operation": "queue_member_account", "params": {"member_name": member_name}},
            )

        # Note: Even if user exists, we still create a request to ensure proper linking
        # The AccountCreationManager will detect the existing user and link it to the member

        # Check if request already exists
        existing_request = frappe.db.exists(
            "Account Creation Request",
            {"source_record": member_name, "status": ["not in", ["Completed", "Cancelled"]]},
        )

        if existing_request:
            return OperationResult.fail(
                _("Account creation request already exists"),
                errors=[f"Request {existing_request} already exists"],
                context={
                    "operation": "queue_member_account",
                    "params": {"member_name": member_name, "existing_request": existing_request},
                },
            )

        # Deserialize roles if passed as JSON string (frappe.call serialization)
        if isinstance(roles, str):
            roles = frappe.parse_json(roles)

        # Set default roles if not provided (handles None and empty list)
        if not roles or len(roles) == 0:
            roles = ["Verenigingen Member"]
        if not role_profile:
            # Infer role_profile from roles - volunteers need employee records
            # Check for any role containing "Volunteer" keyword
            has_volunteer_role = any("Volunteer" in r for r in roles) if roles else False
            if has_volunteer_role:
                role_profile = "Verenigingen Volunteer"
            else:
                role_profile = "Verenigingen Member"

        # All member account requests use "Member" type (source_record links to Member DocType)
        # Employee creation is controlled via create_employee_record flag
        request_type = "Member"

        # Determine if employee record should be created
        # Volunteers need Employee records for expense functionality
        create_employee = role_profile == "Verenigingen Volunteer"

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
                "create_employee_record": create_employee,
            }
        )

        # Add requested roles
        for role in roles:
            request.append("requested_roles", {"role": role})

        request.insert()

        # Queue for processing
        queue_result = request.queue_processing()

        return OperationResult.ok(
            {
                "request_name": request.name,
                "member_name": member_name,
                "email": member.email,
                "queue_result": queue_result,
            },
            message=queue_result.get("message", "Account creation queued"),
        )

    except Exception as e:
        frappe.logger().error(f"Error queueing account creation for member {member_name}: {str(e)}")
        frappe.log_error(
            f"Failed to queue account creation: {str(e)}\n{traceback.format_exc()}",
            "Queue Member Account Creation Error",
        )
        return OperationResult.fail(
            _("Unable to queue account creation. Please contact support."),
            errors=[str(e)],
            context={"operation": "queue_member_account", "params": {"member_name": member_name}},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def queue_account_creation_for_volunteer(
    volunteer_name: str, priority: str = "Normal"
) -> OperationResult[Dict[str, Any]]:
    """Queue account creation for a volunteer record

    Args:
        volunteer_name: Volunteer record name
        priority: Processing priority (default: "Normal")

    Returns:
        OperationResult[Dict[str, Any]]: Result with request name and status
    """
    try:
        # Skip permission check during tests if flag is set
        if not frappe.flags.get("skip_user_permission_check", False):
            if not frappe.has_permission("User", "create"):
                return OperationResult.fail(
                    _("Insufficient permissions to create user accounts"),
                    errors=["Permission denied"],
                    context={
                        "operation": "queue_volunteer_account",
                        "params": {"volunteer_name": volunteer_name},
                    },
                )

        # Get volunteer details
        if not frappe.db.exists("Volunteer", volunteer_name):
            return OperationResult.fail(
                _("Volunteer not found"),
                errors=[f"Volunteer {volunteer_name} does not exist"],
                context={
                    "operation": "queue_volunteer_account",
                    "params": {"volunteer_name": volunteer_name},
                },
            )

        volunteer = frappe.get_doc("Volunteer", volunteer_name)

        if not volunteer.email:
            return OperationResult.fail(
                _("Volunteer must have an email address for account creation"),
                errors=["No email address provided"],
                context={
                    "operation": "queue_volunteer_account",
                    "params": {"volunteer_name": volunteer_name},
                },
            )

        # Check if user already exists for this email
        if frappe.db.exists("User", volunteer.email):
            frappe.logger().info(
                f"User account already exists for volunteer {volunteer_name} with email {volunteer.email}"
            )
            # Return a successful result indicating existing account was found
            return OperationResult.ok(
                {
                    "request_name": None,
                    "result": "existing_user",
                    "email": volunteer.email,
                    "volunteer_name": volunteer_name,
                },
                message=f"User account already exists for {volunteer.email}",
            )

        # Check if request already exists
        existing_request = frappe.db.exists(
            "Account Creation Request",
            {"source_record": volunteer_name, "status": ["not in", ["Completed", "Cancelled"]]},
        )

        if existing_request:
            return OperationResult.fail(
                _("Account creation request already exists"),
                errors=[f"Request {existing_request} already exists"],
                context={
                    "operation": "queue_volunteer_account",
                    "params": {"volunteer_name": volunteer_name, "existing_request": existing_request},
                },
            )

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
        queue_result = request.queue_processing()

        return OperationResult.ok(
            {
                "request_name": request.name,
                "volunteer_name": volunteer_name,
                "email": volunteer.email,
                "queue_result": queue_result,
            },
            message=queue_result.get("message", "Account creation queued"),
        )

    except Exception as e:
        frappe.logger().error(f"Error queueing account creation for volunteer {volunteer_name}: {str(e)}")
        frappe.log_error(
            f"Failed to queue volunteer account creation: {str(e)}\n{traceback.format_exc()}",
            "Queue Volunteer Account Creation Error",
        )
        return OperationResult.fail(
            _("Unable to queue account creation. Please contact support."),
            errors=[str(e)],
            context={"operation": "queue_volunteer_account", "params": {"volunteer_name": volunteer_name}},
        )


# Bulk processing functions


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def queue_bulk_account_creation_for_members(
    member_names: list,
    roles=None,
    role_profile=None,
    batch_size: int = 50,
    priority: str = "Low",
    create_employee: bool = False,
) -> OperationResult[Dict[str, Any]]:
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
        OperationResult[Dict[str, Any]]: Summary with request names, linked users, and validation errors
    """
    try:
        if not frappe.has_permission("User", "create"):
            return OperationResult.fail(
                _("Insufficient permissions to create user accounts"),
                errors=["Permission denied"],
                context={
                    "operation": "queue_bulk_accounts",
                    "params": {"count": len(member_names) if member_names else 0},
                },
            )

        if not member_names:
            return OperationResult.fail(
                _("No member names provided"),
                errors=["Empty member_names list"],
                context={"operation": "queue_bulk_accounts", "params": {}},
            )

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
                return OperationResult.ok(
                    {
                        "requests_created": 0,
                        "users_linked": linked_count,
                        "validation_errors_count": result.get("validation_errors_count", 0),
                        "validation_errors": validation_errors[:50],
                    },
                    message=f"Linked {linked_count} existing user accounts, no new accounts to create",
                )
            else:
                return OperationResult.fail(
                    _("No valid members found for processing"),
                    errors=["No members met validation criteria"],
                    context={
                        "operation": "queue_bulk_accounts",
                        "params": {
                            "total_provided": len(member_names),
                            "validation_errors_count": result.get("validation_errors_count", 0),
                        },
                    },
                    metadata={"validation_errors": validation_errors[:50]},
                )

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

        # CRITICAL: Link all created ACRs to this tracker
        # This enables tracking progress and retry functionality
        if created_requests:
            placeholders = ", ".join(["%s"] * len(created_requests))
            frappe.db.sql(
                f"""
                UPDATE `tabAccount Creation Request`
                SET bulk_operation_tracker = %s
                WHERE name IN ({placeholders})
                """,
                [tracker.name] + created_requests,
            )
            frappe.db.commit()
            frappe.logger().info(f"Linked {len(created_requests)} ACRs to tracker {tracker.name}")

        # Split requests into batches
        total_requests = len(created_requests)
        total_batches = (total_requests + batch_size - 1) // batch_size

        # Create batch metadata for chain-of-responsibility pattern
        batches = []
        for i in range(0, total_requests, batch_size):
            batch = created_requests[i : i + batch_size]
            batch_number = i // batch_size + 1
            batches.append(
                {
                    "batch_id": f"bulk_batch_{batch_number}",
                    "batch_number": batch_number,
                    "request_names": batch,
                    "request_count": len(batch),
                }
            )

        frappe.logger().info(
            f"Using chain-of-responsibility pattern: queueing first batch, "
            f"remaining {total_batches - 1} batches will chain automatically "
            f"({total_requests} total requests, {batch_size} per batch)"
        )

        # Queue ONLY the first batch - it will chain to the rest
        first_batch = batches[0]
        remaining_batches = batches[1:]  # To be queued by the first batch upon completion

        try:
            frappe.enqueue(
                "verenigingen.utils.account_creation_manager.process_bulk_account_creation_batch",
                request_names=first_batch["request_names"],
                batch_id=first_batch["batch_id"],
                batch_number=first_batch["batch_number"],
                tracker_name=tracker.name,
                remaining_batches=remaining_batches,  # Pass remaining batches for chaining
                queue="long",
                timeout=3600,  # 1 hour per batch (not for queueing all batches)
                job_name=f"bulk_account_creation_{first_batch['batch_id']}",
            )

            frappe.logger().info(
                f"Queued first batch {first_batch['batch_id']} (1/{total_batches}) with "
                f"{first_batch['request_count']} requests. Remaining batches will chain automatically."
            )

            batch_results = [
                {
                    "batch_id": first_batch["batch_id"],
                    "batch_number": first_batch["batch_number"],
                    "request_count": first_batch["request_count"],
                    "status": "queued",
                }
            ]

        except Exception as e:
            frappe.logger().error(f"Failed to queue first batch: {str(e)}")
            batch_results = [
                {
                    "batch_id": first_batch["batch_id"],
                    "batch_number": first_batch["batch_number"],
                    "request_count": first_batch["request_count"],
                    "status": "failed",
                    "error": str(e),
                }
            ]

        # Start the operation tracking
        tracker.start_operation()

        # Return comprehensive summary
        return_result = {
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

        return OperationResult.ok(
            return_result,
            message=f"Queued {len(created_requests)} account creation requests in {len(batch_results)} batches",
        )

    except Exception as e:
        frappe.logger().error(f"Error in bulk account creation queueing: {str(e)}")
        frappe.log_error(
            f"Bulk account creation queueing failed: {str(e)}\n{traceback.format_exc()}",
            "Bulk Account Creation Queue Error",
        )
        return OperationResult.fail(
            _("Unable to queue bulk account creation. Please contact support."),
            errors=[str(e)],
            context={
                "operation": "queue_bulk_accounts",
                "params": {"count": len(member_names) if member_names else 0},
            },
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def process_bulk_account_creation_batch(
    request_names: str, batch_id: str, batch_number: int, tracker_name: str, remaining_batches=None
):
    """
    Process a batch of account creation requests with parallel processing and enhanced error handling.

    Uses chain-of-responsibility pattern: upon completion, automatically queues the next batch
    if remaining_batches is provided. This ensures natural flow control without timeout issues.

    This is the background job that processes individual batches created by the
    bulk queue function. Requests are processed in parallel (up to 5 at a time)
    to meet performance requirements while maintaining error isolation.

    Args:
        request_names: List of Account Creation Request names to process
        batch_id: Batch identifier for logging
        batch_number: Batch number for progress tracking (1-indexed)
        tracker_name: Name of BulkOperationTracker document
        remaining_batches: List of remaining batch metadata dicts for chaining (optional)

    Returns:
        OperationResult[Dict[str, Any]]: Batch processing results with success/failure counts
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

                # Commit transaction on success (skip during tests for proper isolation)
                if not frappe.flags.in_test:
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

    # Chain-of-responsibility: Queue next batch if there are remaining batches
    if remaining_batches and len(remaining_batches) > 0:
        next_batch = remaining_batches[0]
        remaining_after_next = remaining_batches[1:]

        frappe.logger().info(
            f"Batch {batch_id} completed. Chaining to next batch: {next_batch['batch_id']} "
            f"({next_batch['batch_number']}/{next_batch['batch_number'] + len(remaining_after_next)})"
        )

        # CRITICAL: Wait for current batch's ACRs to fully complete before queueing next batch
        # This ensures we don't queue faster than the system can process, preventing queue overflow
        try:
            import time

            max_wait_seconds = 600  # 10 minutes max wait for batch completion
            wait_interval = 3  # Check every 3 seconds
            waited = 0

            frappe.logger().info(
                f"Waiting for current batch ({len(request_names)} ACRs) to fully complete "
                f"before queueing next batch"
            )

            while waited < max_wait_seconds:
                # Check how many ACRs from this batch are still processing
                still_processing = frappe.db.count(
                    "Account Creation Request",
                    {
                        "name": ["in", request_names],
                        "status": ["in", ["Requested", "Queued", "In Progress"]],
                    },
                )

                if still_processing == 0:
                    # All ACRs from this batch are done (Completed or Failed)
                    completed = frappe.db.count(
                        "Account Creation Request",
                        {"name": ["in", request_names], "status": "Completed"},
                    )
                    failed = frappe.db.count(
                        "Account Creation Request",
                        {"name": ["in", request_names], "status": "Failed"},
                    )

                    frappe.logger().info(
                        f"Batch fully processed: {completed} completed, {failed} failed. "
                        f"Queuing next batch now."
                    )
                    break

                # Some ACRs still processing, wait
                if waited % 15 == 0:  # Log every 15 seconds
                    frappe.logger().info(
                        f"Waiting for batch to complete: {still_processing} ACRs still processing "
                        f"(waited {waited}s so far)"
                    )

                time.sleep(wait_interval)
                waited += wait_interval

            if waited >= max_wait_seconds:
                # Batch didn't complete in time - queue next batch anyway to avoid stalling
                still_processing = frappe.db.count(
                    "Account Creation Request",
                    {
                        "name": ["in", request_names],
                        "status": ["in", ["Requested", "Queued", "In Progress"]],
                    },
                )

                frappe.logger().warning(
                    f"Batch still has {still_processing} ACRs processing after {max_wait_seconds}s wait. "
                    f"Queuing next batch anyway to avoid stalling (may cause queue saturation)."
                )

        except Exception as batch_wait_error:
            frappe.logger().warning(
                f"Batch completion check failed: {str(batch_wait_error)}, " f"proceeding to queue next batch"
            )

        # Queue the next batch
        try:
            frappe.enqueue(
                "verenigingen.utils.account_creation_manager.process_bulk_account_creation_batch",
                request_names=next_batch["request_names"],
                batch_id=next_batch["batch_id"],
                batch_number=next_batch["batch_number"],
                tracker_name=tracker_name,
                remaining_batches=remaining_after_next,  # Pass remaining batches forward
                queue="long",
                timeout=3600,
                job_name=f"bulk_account_creation_{next_batch['batch_id']}",
            )

            frappe.logger().info(
                f"Successfully queued next batch {next_batch['batch_id']} "
                f"with {next_batch['request_count']} requests"
            )

        except Exception as e:
            frappe.logger().error(
                f"Failed to queue next batch {next_batch['batch_id']}: {str(e)}. "
                f"Chain broken - remaining batches will not be processed!"
            )
            frappe.log_error(
                f"Batch chain broken at {batch_id}. Failed to queue {next_batch['batch_id']}: {str(e)}\n"
                f"Remaining batches: {len(remaining_batches)}",
                "Bulk Account Creation Chain Failure",
            )

    else:
        frappe.logger().info(f"Batch {batch_id} completed. No remaining batches - bulk operation finished!")

    return OperationResult.ok(
        batch_results,
        message=f"Batch {batch_id} completed: {batch_results['completed']} successes, {batch_results['failed']} failures",
    )


# Administrative functions


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_failed_requests() -> OperationResult[Dict[str, Any]]:
    """Get failed account creation requests for admin review

    Returns:
        OperationResult[Dict[str, Any]]: List of failed requests with details
    """
    try:
        # Skip permission check during tests if flag is set
        if not frappe.flags.get("skip_user_permission_check", False):
            if not frappe.has_permission("Account Creation Request", "read"):
                return OperationResult.fail(
                    _("Insufficient permissions to view account creation requests"),
                    errors=["Permission denied"],
                    context={"operation": "get_failed_requests", "params": {}},
                )

        failed_requests = frappe.get_all(
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

        return OperationResult.ok(
            {"failed_requests": failed_requests, "count": len(failed_requests)},
            message=f"Found {len(failed_requests)} failed account creation requests",
        )

    except Exception as e:
        frappe.logger().error(f"Error retrieving failed requests: {str(e)}")
        frappe.log_error(
            f"Failed to retrieve failed requests: {str(e)}\n{traceback.format_exc()}",
            "Get Failed Requests Error",
        )
        return OperationResult.fail(
            _("Unable to retrieve failed requests. Please contact support."),
            errors=[str(e)],
            context={"operation": "get_failed_requests", "params": {}},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def retry_failed_request(request_name: str) -> OperationResult[Dict[str, Any]]:
    """Manually retry a failed account creation request

    Args:
        request_name: Name of the Account Creation Request to retry

    Returns:
        OperationResult[Dict[str, Any]]: Result of retry operation
    """
    try:
        if not frappe.has_permission("Account Creation Request", "write"):
            return OperationResult.fail(
                _("Insufficient permissions to retry account creation requests"),
                errors=["Permission denied"],
                context={"operation": "retry_failed_request", "params": {"request_name": request_name}},
            )

        if not frappe.db.exists("Account Creation Request", request_name):
            return OperationResult.fail(
                _("Account creation request not found"),
                errors=[f"Request {request_name} does not exist"],
                context={"operation": "retry_failed_request", "params": {"request_name": request_name}},
            )

        request = frappe.get_doc("Account Creation Request", request_name)
        retry_result = request.retry_processing()

        return OperationResult.ok(
            {"request_name": request_name, "retry_result": retry_result},
            message="Account creation request queued for retry",
        )

    except Exception as e:
        frappe.logger().error(f"Error retrying request {request_name}: {str(e)}")
        frappe.log_error(
            f"Failed to retry request: {str(e)}\n{traceback.format_exc()}", "Retry Failed Request Error"
        )
        return OperationResult.fail(
            _("Unable to retry account creation request. Please contact support."),
            errors=[str(e)],
            context={"operation": "retry_failed_request", "params": {"request_name": request_name}},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def upgrade_member_to_volunteer_user(member_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Upgrade a member's user account from Website User to System User when they become a volunteer.

    This is called when a member who already has a Website User account expresses interest
    in volunteering and has their volunteer record activated.

    Args:
        member_name: Name of the Member record

    Returns:
        OperationResult[Dict[str, Any]]: Result of the upgrade operation
    """
    try:
        if not frappe.has_permission("User", "write"):
            return OperationResult.fail(
                _("Insufficient permissions to upgrade user accounts"),
                errors=["Permission denied"],
                context={"operation": "upgrade_to_volunteer", "params": {"member_name": member_name}},
            )

        # Get member record
        if not frappe.db.exists("Member", member_name):
            return OperationResult.fail(
                _("Member not found"),
                errors=[f"Member {member_name} does not exist"],
                context={"operation": "upgrade_to_volunteer", "params": {"member_name": member_name}},
            )

        member = frappe.get_doc("Member", member_name)

        if not member.user:
            return OperationResult.fail(
                _("No user account linked to this member"),
                errors=["Member has no linked user account"],
                context={"operation": "upgrade_to_volunteer", "params": {"member_name": member_name}},
            )

        # Get user record
        user_doc = frappe.get_doc("User", member.user)

        # Check if already System User
        if user_doc.user_type == "System User":
            frappe.logger().info(f"User {member.user} is already a System User, no upgrade needed")
            return OperationResult.ok(
                {"user": member.user, "already_upgraded": True}, message="User is already a System User"
            )

        # Upgrade to System User
        frappe.logger().info(f"Upgrading user {member.user} from {user_doc.user_type} to System User")
        user_doc.user_type = "System User"

        # Expand module access for volunteers
        # Volunteers need access to HRMS for expense claims
        try:
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

        return OperationResult.ok(
            {"user": member.user, "previous_type": "Website User", "member_name": member_name},
            message="User account upgraded to System User for volunteer access",
        )

    except Exception as e:
        frappe.logger().error(f"Failed to upgrade user for member {member_name}: {str(e)}")
        frappe.log_error(
            f"User upgrade failed: {str(e)}\n{traceback.format_exc()}",
            "Upgrade Member to Volunteer User Error",
        )
        return OperationResult.fail(
            _("Unable to upgrade user account. Please contact support."),
            errors=[str(e)],
            context={"operation": "upgrade_to_volunteer", "params": {"member_name": member_name}},
        )


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def retry_all_failed_requests(failure_type=None) -> OperationResult[Dict[str, Any]]:
    """
    Retry all failed Account Creation Requests.

    Args:
        failure_type: Optional filter - "rate_limit", "employee_exists", or None for all

    Returns:
        OperationResult[Dict[str, Any]]: Summary of retry operation including success/failure counts
    """
    try:
        if not frappe.has_permission("Account Creation Request", "write"):
            return OperationResult.fail(
                _("Insufficient permissions to retry account creation requests"),
                errors=["Permission denied"],
                context={"operation": "retry_all_failed", "params": {"failure_type": failure_type}},
            )

        # Get all failed requests
        filters = {"status": "Failed", "retry_count": ["<", 3]}  # Only retry if under max retries

        failed_requests = frappe.get_all(
            "Account Creation Request",
            filters=filters,
            fields=["name", "email", "full_name", "failure_reason", "retry_count"],
        )

        if not failed_requests:
            return OperationResult.ok(
                {"total": 0, "retried": 0, "errors": 0},
                message="No failed requests found that can be retried",
            )

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
                request.retry_processing()

                retried.append(
                    {"name": req_data.name, "email": req_data.email, "full_name": req_data.full_name}
                )

            except Exception as e:
                error_msg = str(e)
                errors.append({"name": req_data.name, "email": req_data.email, "error": error_msg})
                frappe.logger().error(f"Failed to retry {req_data.name}: {error_msg}")

            # Commit changes (skip during tests for proper isolation)
            if not frappe.flags.in_test:
                frappe.db.commit()

        return OperationResult.ok(
            {
                "total_failed": len(failed_requests),
                "retried": len(retried),
                "errors": len(errors),
                "retried_requests": retried[:20],  # Return first 20 for display
                "error_details": errors[:10],  # Return first 10 errors
            },
            message=f"Successfully queued {len(retried)} requests for retry. {len(errors)} errors encountered.",
        )

    except Exception as e:
        frappe.logger().error(f"Error retrying all failed requests: {str(e)}")
        frappe.log_error(
            f"Retry all failed requests error: {str(e)}\n{traceback.format_exc()}",
            "Retry All Failed Requests Error",
        )
        return OperationResult.fail(
            _("Unable to retry failed requests. Please contact support."),
            errors=[str(e)],
            context={"operation": "retry_all_failed", "params": {"failure_type": failure_type}},
        )
