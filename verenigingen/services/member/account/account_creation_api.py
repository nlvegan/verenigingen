"""
Account Creation API

Whitelisted API / queue / retry layer for account creation. Split out of
account_creation_manager.py (audit T4.6) — that module now holds only the
AccountCreationManager pipeline class; this module holds the public-facing
endpoints that create, queue, batch and retry Account Creation Requests and
drive the pipeline class.

ERROR HANDLING PATTERN:
All whitelisted API endpoints in this module follow the OperationResult pattern:
- Return type: OperationResult[Dict[str, Any]]
- Never throw exceptions - all errors wrapped in OperationResult.fail()
- Consistent metadata with context dict: {"operation": "...", "params": {...}}
- Generic user-facing messages with technical details in errors list
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now

from verenigingen.services.member.account.account_creation_manager import AccountCreationManager
from verenigingen.utils.constants import Roles
from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api

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

    except frappe.DoesNotExistError as e:
        # The request (or its source record) no longer exists — a benign race:
        # the request was cancelled/deleted, or (in tests) rolled back before this
        # enqueued job ran. There is nothing to process, so this is NOT an Error
        # Log-worthy failure; logging it at ERROR previously leaked across test
        # boundaries (the async-after-rollback "ACR-... not found" artifact). Log
        # at debug and return a clean failure result without polluting the Error Log.
        frappe.logger().debug(f"Account creation job skipped for {request_name}: {str(e)}")
        return OperationResult.fail(
            _("Account creation request no longer exists."),
            errors=[str(e)],
            context={"operation": "process_account_creation", "params": {"request_name": request_name}},
        )

    except Exception as e:
        frappe.logger().error(f"Account creation job failed for {request_name}: {str(e)}")
        frappe.log_error(
            title="Account Creation Request Processing Error",
            message=f"Account creation processing failed: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            _("Unable to process account creation request. Please contact support."),
            errors=[str(e)],
            context={"operation": "process_account_creation", "params": {"request_name": request_name}},
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
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
            requests_volunteer_role = bool(roles) and Roles.VOLUNTEER in roles
            if requests_volunteer_role:
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
            title="Queue Member Account Creation Error",
            message=f"Failed to queue account creation: {str(e)}\n{traceback.format_exc()}",
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
            title="Queue Volunteer Account Creation Error",
            message=f"Failed to queue volunteer account creation: {str(e)}\n{traceback.format_exc()}",
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
                "verenigingen.services.member.account.account_creation_api.process_bulk_account_creation_batch",
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
            title="Bulk Account Creation Queue Error",
            message=f"Bulk account creation queueing failed: {str(e)}\n{traceback.format_exc()}",
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
    request_names: list, batch_id: str, batch_number: int, tracker_name: str, remaining_batches=None
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

            # Start transaction for this request. Safe: this runs in a worker
            # thread that called frappe.connect() itself six lines up, so the
            # connection is fresh and transaction_writes is 0 by construction.
            frappe.db.begin()  # db-begin-ok: own-connection

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
            title="Bulk Account Creation Batch Errors",
            message=(
                f"Batch {batch_id} had {batch_results['failed']} failures:\n"
                + "\n".join(batch_results["errors"][:10])  # Log first 10 errors
            ),
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
                "verenigingen.services.member.account.account_creation_api.process_bulk_account_creation_batch",
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
                title="Bulk Account Creation Chain Failure",
                message=(
                    f"Batch chain broken at {batch_id}. Failed to queue {next_batch['batch_id']}: "
                    f"{str(e)}\nRemaining batches: {len(remaining_batches)}"
                ),
            )
            try:
                tracker = frappe.get_doc("Bulk Operation Tracker", tracker_name)
                tracker.add_comment(
                    "Comment",
                    f"Chain broken after batch {batch_id}: failed to queue {next_batch['batch_id']}. "
                    f"{len(remaining_batches)} remaining batches will not be processed.",
                )
                tracker.save()
            except Exception:
                pass

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
            title="Get Failed Requests Error",
            message=f"Failed to retrieve failed requests: {str(e)}\n{traceback.format_exc()}",
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
            title="Retry Failed Request Error",
            message=f"Failed to retry request: {str(e)}\n{traceback.format_exc()}",
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
            title="Upgrade Member to Volunteer User Error",
            message=f"User upgrade failed: {str(e)}\n{traceback.format_exc()}",
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
            title="Retry All Failed Requests Error",
            message=f"Retry all failed requests error: {str(e)}\n{traceback.format_exc()}",
        )
        return OperationResult.fail(
            _("Unable to retry failed requests. Please contact support."),
            errors=[str(e)],
            context={"operation": "retry_all_failed", "params": {"failure_type": failure_type}},
        )
