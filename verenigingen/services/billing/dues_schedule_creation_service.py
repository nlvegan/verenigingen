# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
DuesScheduleCreationService - Reliable dues schedule creation with retry logic.

Provides a production-grade service for creating membership dues schedules with:
- Background job retry using frappe.enqueue()
- Exponential backoff for transient failures
- Structured error handling and alerting
- Job status tracking and monitoring

Replaces the problematic cache-based retry queue with proper background job processing.
"""

from typing import Any, ClassVar, Dict, Optional

import frappe
from frappe.utils import now


class CreationResult:
    """
    Result object for dues schedule creation operations.

    Provides structured outcome with success status, schedule name,
    and detailed error information for diagnostics.

    Attributes:
        success: Whether creation succeeded
        schedule_name: Name of created schedule (if successful)
        error: Error message (if failed)
        error_category: Classification ("config", "validation", "system", "duplicate")
        retry_job_id: Background job ID for retry (if enqueued)
    """

    def __init__(
        self,
        success: bool,
        schedule_name: Optional[str] = None,
        error: Optional[str] = None,
        error_category: Optional[str] = None,
        retry_job_id: Optional[str] = None,
        **metadata: Any,
    ):
        """
        Initialize creation result.

        Args:
            success: Whether creation succeeded
            schedule_name: Name of created schedule (if successful)
            error: Error message (if failed)
            error_category: Classification of error
            retry_job_id: Background job ID for retry
            **metadata: Additional context for debugging
        """
        self.success = success
        self.schedule_name = schedule_name
        self.error = error
        self.error_category = error_category
        self.retry_job_id = retry_job_id
        self.metadata = metadata

    def to_dict(self) -> Dict:
        """Convert to dict for serialization."""
        return {
            "success": self.success,
            "schedule_name": self.schedule_name,
            "error": self.error,
            "error_category": self.error_category,
            "retry_job_id": self.retry_job_id,
            **self.metadata,
        }

    def __repr__(self):
        if self.success:
            return f"CreationResult(success=True, schedule_name='{self.schedule_name}')"
        return f"CreationResult(success=False, error='{self.error}', category='{self.error_category}')"


class DuesScheduleCreationService:
    """
    Service for reliable membership dues schedule creation with retry logic.

    Handles creation of dues schedules from templates with automatic retry
    for transient failures using frappe's background job queue.

    Features:
    - Immediate creation attempt with fallback to background retry
    - Exponential backoff (retry_count: 0→1min, 1→5min, 2→30min)
    - Maximum 3 retry attempts before alerting administrators
    - Structured error categorization for debugging
    - Job tracking for monitoring and observability

    Example:
        service = DuesScheduleCreationService()
        result = service.create_schedule_with_retry(
            member_name="MBR-001",
            membership_name="MEM-001",
            membership_type="Standard Member"
        )
        if result.success:
            print(f"Created: {result.schedule_name}")
        else:
            print(f"Failed: {result.error}, retry job: {result.retry_job_id}")
    """

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAYS: ClassVar[list[int]] = [60, 300, 1800]  # 1min, 5min, 30min in seconds
    QUEUE_CONGESTION_THRESHOLD = 500  # Max pending jobs before backpressure

    # Circuit breaker configuration
    CIRCUIT_BREAKER_THRESHOLD = 10  # Consecutive failures before opening circuit
    CIRCUIT_BREAKER_WINDOW = 300  # 5 minutes (in seconds)
    CIRCUIT_BREAKER_CACHE_KEY = "dues_schedule_circuit_breaker"

    def create_schedule_with_retry(
        self,
        member_name: str,
        membership_name: str,
        membership_type: str,
        custom_amount: Optional[float] = None,
        custom_amount_reason: Optional[str] = None,
        custom_amount_approved: int = 0,
        retry_count: int = 0,
    ) -> CreationResult:
        """
        Create dues schedule with automatic retry on failure.

        Attempts immediate creation. If it fails with a retryable error,
        enqueues a background job with exponential backoff.

        Args:
            member_name: Member document name
            membership_name: Membership document name
            membership_type: Membership type name
            custom_amount: Custom dues amount (optional)
            custom_amount_reason: Reason for custom amount (optional)
            custom_amount_approved: Whether custom amount is approved (optional)
            retry_count: Current retry attempt number (internal use)

        Returns:
            CreationResult with success status, schedule name, or retry job ID
        """
        # Input validation
        if not member_name or not member_name.strip():
            return CreationResult(
                success=False, error="Invalid member_name: cannot be empty", error_category="validation"
            )

        if not membership_name or not membership_name.strip():
            return CreationResult(
                success=False, error="Invalid membership_name: cannot be empty", error_category="validation"
            )

        if not membership_type or not membership_type.strip():
            return CreationResult(
                success=False, error="Invalid membership_type: cannot be empty", error_category="validation"
            )

        if custom_amount is not None and custom_amount < 0:
            return CreationResult(
                success=False,
                error=f"Invalid custom_amount: {custom_amount} (must be non-negative)",
                error_category="validation",
            )

        # Clamp retry_count to valid range
        if retry_count < 0 or retry_count > self.MAX_RETRIES:
            frappe.logger().warning(
                f"[DUES SCHEDULE] Invalid retry_count {retry_count} for {member_name}, "
                f"clamping to [0, {self.MAX_RETRIES}]"
            )
            retry_count = max(0, min(retry_count, self.MAX_RETRIES))

        try:
            # Check circuit breaker before attempting creation
            if self._should_circuit_break():
                return CreationResult(
                    success=False,
                    error="Circuit breaker is open due to repeated failures. Retries suspended temporarily.",
                    error_category="system",
                    circuit_breaker_open=True,
                    retry_count=retry_count,
                )

            # Check if schedule already exists (idempotency)
            existing_schedule = frappe.db.get_value(
                "Membership Dues Schedule", {"member": member_name, "is_template": 0}, "name"
            )

            if existing_schedule:
                frappe.logger().info(
                    f"[DUES SCHEDULE] Schedule already exists for {member_name}: {existing_schedule}"
                )
                # Success - reset circuit breaker
                self._record_success()
                return CreationResult(
                    success=True,
                    schedule_name=existing_schedule,
                    already_exists=True,
                )

            # Attempt creation
            from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule import (
                MembershipDuesSchedule,
            )

            kwargs = {
                "membership_type": membership_type,
                "membership_name": membership_name,
            }

            if custom_amount and custom_amount > 0:
                kwargs["custom_amount"] = custom_amount
                kwargs["custom_amount_reason"] = custom_amount_reason or "Custom amount"
                kwargs["custom_amount_approved"] = custom_amount_approved

            schedule_name = MembershipDuesSchedule.create_from_template(member_name, **kwargs)

            frappe.logger().info(
                f"[DUES SCHEDULE] Successfully created {schedule_name} for member {member_name}"
            )

            # Reset circuit breaker on successful creation
            self._record_success()

            return CreationResult(success=True, schedule_name=schedule_name, retry_count=retry_count)

        except Exception as e:
            error_str = str(e)
            error_category = self._categorize_error(error_str)

            frappe.logger().warning(
                f"[DUES SCHEDULE] Creation failed for {member_name} (attempt {retry_count + 1}): {error_str}"
            )

            # Record failure for circuit breaker tracking
            self._record_failure()

            # Determine if error is retryable
            if self._is_retryable_error(error_category) and retry_count < self.MAX_RETRIES:
                # Enqueue retry with exponential backoff
                retry_job_id = self._enqueue_retry(
                    member_name=member_name,
                    membership_name=membership_name,
                    membership_type=membership_type,
                    custom_amount=custom_amount,
                    custom_amount_reason=custom_amount_reason,
                    custom_amount_approved=custom_amount_approved,
                    retry_count=retry_count + 1,
                )

                # Check if retry was deferred due to queue congestion
                if retry_job_id is None:
                    return CreationResult(
                        success=False,
                        error=error_str,
                        error_category=error_category,
                        retry_count=retry_count,
                        will_retry=False,
                        backpressure_applied=True,
                        deferred_to_scheduled_task=True,
                    )

                return CreationResult(
                    success=False,
                    error=error_str,
                    error_category=error_category,
                    retry_job_id=retry_job_id,
                    retry_count=retry_count,
                    will_retry=True,
                )
            else:
                # Max retries reached or non-retryable error
                self._create_failure_alert(
                    member_name=member_name,
                    membership_name=membership_name,
                    error=error_str,
                    error_category=error_category,
                    retry_count=retry_count,
                )

                return CreationResult(
                    success=False,
                    error=error_str,
                    error_category=error_category,
                    retry_count=retry_count,
                    max_retries_reached=retry_count >= self.MAX_RETRIES,
                )

    def _enqueue_retry(
        self,
        member_name: str,
        membership_name: str,
        membership_type: str,
        custom_amount: Optional[float],
        custom_amount_reason: Optional[str],
        custom_amount_approved: int,
        retry_count: int,
    ) -> str:
        """
        Enqueue background job for retry with exponential backoff.

        Implements queue backpressure to prevent congestion during bulk failures.

        Args:
            All parameters from create_schedule_with_retry

        Returns:
            Job ID for tracking, or None if backpressure applied
        """
        # Check for queue congestion before enqueuing
        try:
            from frappe.utils.background_jobs import get_redis_conn
            from rq import Queue

            redis_conn = get_redis_conn()
            queue = Queue("long", connection=redis_conn)
            pending_jobs = len(queue)

            if pending_jobs > self.QUEUE_CONGESTION_THRESHOLD:
                frappe.logger().warning(
                    f"[DUES SCHEDULE] Queue congestion detected ({pending_jobs} jobs pending). "
                    f"Deferring retry for {member_name} to prevent overload. "
                    f"This will be retried by the scheduled auto-creator task."
                )
                # Don't enqueue - let scheduled task handle it later
                return None
        except Exception as queue_check_error:
            # If queue check fails, proceed with enqueue (fail open)
            frappe.logger().warning(
                f"[DUES SCHEDULE] Could not check queue depth: {queue_check_error}. Proceeding with enqueue."
            )

        delay_seconds = self.RETRY_DELAYS[min(retry_count - 1, len(self.RETRY_DELAYS) - 1)]

        job = frappe.enqueue(
            "verenigingen.services.billing.dues_schedule_creation_service.retry_create_dues_schedule_job",
            queue="long",
            timeout=300,
            now=False,
            enqueue_after_commit=True,
            at_front=False,
            job_name=f"retry_dues_schedule_{member_name}_{retry_count}",
            # Job arguments
            member_name=member_name,
            membership_name=membership_name,
            membership_type=membership_type,
            custom_amount=custom_amount,
            custom_amount_reason=custom_amount_reason,
            custom_amount_approved=custom_amount_approved,
            retry_count=retry_count,
            delay_seconds=delay_seconds,  # Pass delay to job
        )

        # Get actual RQ job ID from returned Job object
        job_id = job.id if hasattr(job, "id") else f"retry_dues_schedule_{member_name}_{retry_count}"

        frappe.logger().info(
            f"[DUES SCHEDULE] Enqueued retry {retry_count} for {member_name} "
            f"with {delay_seconds}s delay (job ID: {job_id})"
        )

        return job_id

    def _categorize_error(self, error_str: str) -> str:
        """
        Categorize error for handling decisions.

        Args:
            error_str: Error message

        Returns:
            Category: "config", "validation", "system", "duplicate"
        """
        error_lower = error_str.lower()

        if "already has a dues schedule" in error_lower or "already exists" in error_lower:
            return "duplicate"
        elif "template" in error_lower or "suggested_amount" in error_lower:
            return "config"
        elif "validation" in error_lower or "invalid" in error_lower:
            return "validation"
        else:
            return "system"

    def _is_retryable_error(self, error_category: str) -> bool:
        """
        Determine if error is retryable.

        Args:
            error_category: Error category from _categorize_error

        Returns:
            True if error may resolve with retry
        """
        # Config errors (missing template) may be fixed by admin
        # System errors (DB locks, network) are transient
        # Validation and duplicate errors are permanent
        return error_category in ("config", "system")

    def _should_circuit_break(self) -> bool:
        """
        Check if circuit breaker should prevent retries.

        Circuit breaker opens after repeated failures to prevent
        cascade failures during systemic issues (e.g., template deleted).

        Returns:
            True if circuit is open (should NOT retry)
        """
        try:
            failure_count = frappe.cache().get(self.CIRCUIT_BREAKER_CACHE_KEY) or 0
            is_open = failure_count >= self.CIRCUIT_BREAKER_THRESHOLD

            if is_open:
                frappe.logger().warning(
                    f"[DUES SCHEDULE] Circuit breaker OPEN: {failure_count} recent failures. "
                    f"Preventing retries to avoid cascade failure. "
                    f"Will auto-reset in {self.CIRCUIT_BREAKER_WINDOW}s."
                )

            return is_open
        except Exception as e:
            # If cache check fails, fail open (allow retry)
            frappe.logger().warning(
                f"[DUES SCHEDULE] Circuit breaker check failed: {e}. Allowing retry (fail-open)."
            )
            return False

    def _record_failure(self):
        """Record a failure for circuit breaker tracking."""
        try:
            key = self.CIRCUIT_BREAKER_CACHE_KEY
            current_failures = frappe.cache().get(key) or 0
            new_failures = current_failures + 1

            # Set with TTL - automatically resets after window expires
            frappe.cache().set_value(key, new_failures, expires_in_sec=self.CIRCUIT_BREAKER_WINDOW)

            frappe.logger().info(
                f"[DUES SCHEDULE] Circuit breaker: {new_failures} failures "
                f"(threshold: {self.CIRCUIT_BREAKER_THRESHOLD})"
            )
        except Exception as e:
            frappe.logger().warning(f"[DUES SCHEDULE] Could not record failure: {e}")

    def _record_success(self):
        """Record a success - resets circuit breaker."""
        try:
            frappe.cache().delete_value(self.CIRCUIT_BREAKER_CACHE_KEY)
        except Exception as e:
            frappe.logger().warning(f"[DUES SCHEDULE] Could not reset circuit breaker: {e}")

    def _create_failure_alert(
        self, member_name: str, membership_name: str, error: str, error_category: str, retry_count: int
    ):
        """
        Create administrator alert for permanent failures.

        Args:
            member_name: Member document name
            membership_name: Membership document name
            error: Error message
            error_category: Error category
            retry_count: Number of retry attempts made
        """
        import html

        try:
            # Escape all user-controlled data for HTML safety
            safe_member_name = html.escape(member_name)
            safe_membership_name = html.escape(membership_name)
            safe_error = html.escape(error)
            safe_error_category = html.escape(error_category)
            # Create notification for administrators
            notification = frappe.new_doc("Notification Log")
            notification.subject = f"Dues Schedule Creation Failed - {member_name}"
            notification.email_content = f"""
            <h3>Dues Schedule Creation Failed After {retry_count} Retries</h3>

            <p>A dues schedule could not be created for member <strong>{safe_member_name}</strong>
            after {retry_count} retry attempts.</p>

            <table style="border-collapse: collapse; width: 100%; margin: 10px 0;">
                <tr>
                    <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Member:</td>
                    <td style="border: 1px solid #ddd; padding: 8px;">{safe_member_name}</td>
                </tr>
                <tr>
                    <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Membership:</td>
                    <td style="border: 1px solid #ddd; padding: 8px;">{safe_membership_name}</td>
                </tr>
                <tr>
                    <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Error Category:</td>
                    <td style="border: 1px solid #ddd; padding: 8px;">{safe_error_category}</td>
                </tr>
                <tr>
                    <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Error:</td>
                    <td style="border: 1px solid #ddd; padding: 8px;">{safe_error}</td>
                </tr>
                <tr>
                    <td style="border: 1px solid #ddd; padding: 8px; font-weight: bold;">Time:</td>
                    <td style="border: 1px solid #ddd; padding: 8px;">{html.escape(now())}</td>
                </tr>
            </table>

            <p style="margin-top: 20px;">
                <strong>Action Required:</strong><br>
                1. Check the member's configuration and membership type<br>
                2. Verify the dues schedule template exists and is properly configured<br>
                3. Manually create the dues schedule if needed
            </p>

            <p style="margin-top: 15px;">
                <a href="/app/member/{safe_member_name}" style="background: #007bff; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px;">View Member</a>
                <a href="/app/membership/{safe_membership_name}" style="background: #28a745; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px; margin-left: 10px;">View Membership</a>
            </p>
            """

            notification.type = "Alert"
            notification.document_type = "Membership"
            notification.document_name = membership_name
            notification.from_user = "Administrator"

            # Send to administrators
            admin_users = frappe.get_all(
                "User",
                filters={"enabled": 1, "user_type": "System User"},
                or_filters=[
                    ["name", "in", frappe.get_roles("System Manager")],
                    ["name", "in", frappe.get_roles("Verenigingen Administrator")],
                ],
                pluck="name",
            )

            # Use secure document operation instead of permission bypass
            from verenigingen.utils.secure_operations import secure_document_operation

            notification_count = 0
            for admin in admin_users[:5]:  # Limit to 5 admins to avoid spam
                admin_notification = notification.copy()
                admin_notification.for_user = admin

                # Secure notification creation with proper permission validation
                result = secure_document_operation(
                    operation="insert",
                    doc=admin_notification,
                    justification=f"Create dues schedule failure alert for admin {admin} after {retry_count} retries",
                    required_permissions=["Notification Log:create"],
                )

                if result.success:
                    notification_count += 1
                else:
                    frappe.logger().error(
                        f"[DUES SCHEDULE] Failed to create alert for admin {admin}: "
                        f"{'; '.join(result.errors)}"
                    )

            frappe.logger().info(
                f"[DUES SCHEDULE] Created {notification_count}/{len(admin_users[:5])} failure alerts for {member_name}"
            )

        except Exception as alert_error:
            frappe.logger().error(f"[DUES SCHEDULE] Failed to create failure alert: {str(alert_error)}")


# Background job entry point
def retry_create_dues_schedule_job(
    member_name: str,
    membership_name: str,
    membership_type: str,
    custom_amount: Optional[float] = None,
    custom_amount_reason: Optional[str] = None,
    custom_amount_approved: int = 0,
    retry_count: int = 0,
    delay_seconds: int = 0,
):
    """
    Background job entry point for retry operations.

    Called by frappe.enqueue() to retry failed dues schedule creation.
    Implements exponential backoff delay before attempting retry.

    Args:
        All parameters from DuesScheduleCreationService.create_schedule_with_retry
        delay_seconds: Number of seconds to wait before attempting retry
    """
    import time

    frappe.logger().info(f"[DUES SCHEDULE] Background job starting for {member_name} (retry {retry_count})")

    # Implement exponential backoff delay
    if delay_seconds > 0:
        frappe.logger().info(
            f"[DUES SCHEDULE] Waiting {delay_seconds}s before retry {retry_count} for {member_name}"
        )
        time.sleep(delay_seconds)

    service = DuesScheduleCreationService()
    result = service.create_schedule_with_retry(
        member_name=member_name,
        membership_name=membership_name,
        membership_type=membership_type,
        custom_amount=custom_amount,
        custom_amount_reason=custom_amount_reason,
        custom_amount_approved=custom_amount_approved,
        retry_count=retry_count,
    )

    if result.success:
        frappe.logger().info(
            f"[DUES SCHEDULE] Background job succeeded for {member_name}: {result.schedule_name}"
        )
    else:
        frappe.logger().warning(f"[DUES SCHEDULE] Background job failed for {member_name}: {result.error}")

    return result.to_dict()
