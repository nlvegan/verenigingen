"""
Account Creation Manager

This module provides the AccountCreationManager pipeline class — secure,
background-processed account creation for the Verenigingen system. It
addresses critical security vulnerabilities by eliminating permission
bypasses and implementing proper validation, audit trails, and error handling.

The whitelisted API / queue / retry endpoints that drive this class live
in account_creation_api.py (split out under audit T4.6).

Key Features:
- Zero permission bypasses - all operations use proper Frappe security
- Background job processing with comprehensive retry logic
- Detailed status tracking and failure reporting
- Complete audit trail for security compliance
- Transactional processing with rollback capability

Security Model:
- Validates permissions before every operation
- No use of ignore_permissions=True except for system status tracking  # Security: documented in architecture
- Proper role assignment validation
- Complete audit logging

Architecture:
- Request-based processing through Account Creation Request DocType
- Background job execution via Redis queue
- Independent retry capability for each pipeline stage
- Integration with existing Frappe/ERPNext patterns

Author: Verenigingen Development Team
"""

import random
import time
import traceback
from contextlib import contextmanager

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.dutch_name_utils import get_full_last_name
from verenigingen.utils.retry_utilities import execute_with_deadlock_retry


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
                execute_with_deadlock_retry(self.assign_roles_and_profile, "assign_roles_and_profile")
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
                    execute_with_deadlock_retry(self.create_employee_record, "create_employee_record")
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
            # Non-fatal — user still has the basic profile from Phase 1.
            # Also surface as an Error Log entry: the warning-only path lost
            # us a TimestampMismatchError regression for weeks (issue surfaced
            # 2026-04-19 when Customer Group bug stopped masking it).
            frappe.logger().warning(
                f"[ACR PIPELINE] ⚠️ Role profile sync failed for {self.created_user}: {e}"
            )
            frappe.log_error(
                message=f"Phase 3 role profile sync failed for {self.created_user}: {e}",
                title="ACR Pipeline: Phase 3 Role Profile Sync Failed",
            )

    def validate_processing_permissions(self):
        """Validate that processing can proceed with proper permissions.

        The ACR pipeline implements its own role-based authorization rather than
        relying on Frappe's User/Employee doctype perms (which are HR-centric and
        exclude verenigingen roles). The API entry point (e.g.
        queue_account_creation_for_member) is gated by @high_security_api, and
        this method re-checks at job start because the worker runs as
        frappe.session.user.
        """
        frappe.logger().info(f"Validating processing permissions for {self.request_name}")

        # Validate request exists
        if not self.request:
            raise frappe.ValidationError("Cannot validate permissions: Account creation request not loaded")

        # Require proper user context - no Guest access
        if frappe.session.user == "Guest":
            raise frappe.PermissionError("Account creation requires authenticated user")

        # Role-based gate: Verenigingen Staff/Admin/Sys Manager may run the pipeline.
        # Doctype-level User/Employee create perms are NOT used here — they only
        # grant System Manager / HR User / HR Manager respectively, which is the
        # wrong shape for an association-management workflow.
        if not (set(frappe.get_roles()) & Roles.ADMIN_ROLES):
            raise frappe.PermissionError(
                "Account creation requires Verenigingen Staff, Verenigingen Administrator, or System Manager role"
            )

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
                # Security: ACR pipeline is authorization-gated upstream by
                # @high_security_api at the entry point and by
                # validate_processing_permissions() (Roles.ADMIN_ROLES check) at
                # job start. The User doctype only grants create to System
                # Manager, but Verenigingen Staff/Admin must be able to create
                # the user as part of this internal workflow.
                user_doc.insert(ignore_permissions=True)
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

            # User write is restricted to System Manager at the doctype level,
            # but the ACR pipeline persists the role assignment decided by
            # can_assign_role() — the actual authorization gate for which
            # roles may be granted (prevents privilege escalation).
            # Retry logic is handled at higher level via execute_with_deadlock_retry.
            if roles_added or self.request.role_profile:
                frappe.logger().info(
                    f"[ACR PIPELINE] Saving user with roles | "
                    f"User: {self.created_user} | Roles to add: {roles_added} | Profile: {self.request.role_profile}"
                )
                # Security: gated upstream by @high_security_api + validate_processing_permissions; can_assign_role decides which roles are granted.
                user_doc.save(ignore_permissions=True)
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
            # create_user_permission=0: ERPNext's Employee.on_update auto-creates
            # User Permission records when this is 1, but Frappe's
            # add_user_permission() requires User Permission create perm — which
            # Verenigingen Staff/Admin lack. We disable the automatic creation
            # here and explicitly call add_user_permission(..., ignore_permissions=True)
            # below, which produces the same end state without the perm hop.
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
                    "create_user_permission": 0,
                }
            )

            # Add email if available
            if self.request.email:
                employee_doc.personal_email = self.request.email

            # Employee doctype only grants create to HR User / HR Manager,
            # but volunteers need Employee records for expense claims and no
            # Verenigingen role holds HR perms.
            # Security: gated upstream by @high_security_api(MEMBER_DATA) + validate_processing_permissions (Roles.ADMIN_ROLES).
            employee_doc.insert(ignore_permissions=True)

            # Manually create User Permissions that Employee.on_update would
            # have created if create_user_permission=1 — disabled above to
            # avoid the perm-required hook chain. End state matches default
            # ERPNext flow.
            from frappe.permissions import add_user_permission

            # Security: same upstream gates as employee insert; Employee.on_update would do this without ignore_permissions and fail for non-HR roles.
            add_user_permission("Employee", employee_doc.name, self.created_user, ignore_permissions=True)
            # Security: paired with Employee UP above; same authorization rationale.
            add_user_permission("Company", default_company, self.created_user, ignore_permissions=True)

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
        """Check if current user can assign this role.

        System Manager may assign any role. Verenigingen Staff and Verenigingen
        Administrator share the same allow-list — limited to verenigingen-scoped
        roles plus the Employee roles needed for expense functionality. The
        allow-list is intentionally narrow to prevent privilege escalation
        (e.g. Staff cannot grant Administrator or System Manager).
        """
        current_roles = set(frappe.get_roles())

        # System managers can assign any role
        if Roles.SYSTEM_MANAGER in current_roles:
            return True

        # Verenigingen Staff / Administrator can assign verenigingen-scoped roles
        if current_roles & {Roles.VERENIGINGEN_ADMIN, Roles.VERENIGINGEN_STAFF}:
            allowed_roles = {
                "Verenigingen Member",
                "Verenigingen Volunteer",
                Roles.VERENIGINGEN_STAFF,
                "Verenigingen Chapter Board Member",
                "Employee",
                "Employee Self Service",
            }
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

        try:
            frappe.enqueue(
                "verenigingen.services.member.account.account_creation_api.process_account_creation_request",
                request_name=self.request_name,
                queue="long",
                timeout=600,
                job_name=f"account_creation_retry_{self.request_name}",
                at_time=frappe.utils.add_to_date(None, minutes=retry_delay_minutes),
            )
            frappe.logger().info(
                f"Scheduled retry {new_retry_count} for {self.request_name} in {retry_delay_minutes} minutes"
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to enqueue retry for {self.request_name}: {str(e)}",
                "Account Creation Retry Enqueue Failed",
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
