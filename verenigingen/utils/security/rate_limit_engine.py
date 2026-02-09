"""
Rate Limit Engine for API Security Framework

Provides rate limiting with COR (Critical Operation Rules) integration
and context-aware batch support.

DEPENDENCY RULES:
- MAY import from types.py
- MAY use Frappe for DB/cache access
- MUST NOT import from api_security_framework.py (to avoid circular imports)
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.client_ip import get_client_ip
from verenigingen.utils.security.types import ExecutionContext


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    current_count: int
    max_calls: int
    period_seconds: int
    limit_type: str  # "interactive", "batch", "batch_inherited"
    reason: str = ""


class RateLimitEngine:
    """
    Atomic rate limiting with Redis and COR integration.

    INVARIANTS:
    - Rate limits are always enforced via COR records (no hardcoded fallbacks)
    - Missing COR configuration causes request denial (fail-closed)
    - Background jobs use batch limits when configured
    - CRITICAL/HIGH operations inherit interactive limits in batch context if no batch limits configured
    """

    def __init__(self):
        """Initialize rate limit engine."""
        pass

    def check_rate_limit(
        self, operation_key: str, context: ExecutionContext = None, force_check: bool = False
    ) -> RateLimitResult:
        """
        Check if operation is within rate limits.

        Args:
            operation_key: Full operation key (e.g., "module.submodule.function_name")
            context: Execution context (auto-detected if not provided)
            force_check: If True, bypass test environment skip (for testing rate limiting itself)

        Returns:
            RateLimitResult with check outcome

        Raises:
            VPermissionError: If no COR configuration found
        """
        # Skip rate limiting during test execution (unless force_check is True)
        if not force_check and getattr(frappe.flags, "in_test", False):
            return RateLimitResult(
                allowed=True,
                current_count=0,
                max_calls=999,
                period_seconds=3600,
                limit_type="test_bypass",
                reason="Rate limiting skipped in test environment",
            )

        # Extract operation name from operation key
        operation_name = operation_key.split(".")[-1] if "." in operation_key else operation_key

        # Get COR configuration for this operation
        cor_record = self._get_cor_config(operation_name)

        # If no COR found, refuse to proceed (no hardcoded fallback)
        if not cor_record:
            raise VPermissionError(
                _("No rate limiting configuration found for operation: {0}").format(operation_name)
            )

        # Detect execution context if not provided
        if context is None:
            context = self._detect_execution_context()

        # Determine which rate limits to apply based on context
        max_calls, period_seconds, limit_type = self._get_effective_limits(
            cor_record, context, operation_name
        )

        # If limit_type is "bypass", allow without rate limiting
        if limit_type == "bypass":
            return RateLimitResult(
                allowed=True,
                current_count=0,
                max_calls=max_calls,
                period_seconds=period_seconds,
                limit_type=limit_type,
                reason="Rate limiting bypassed for batch context with no batch limits",
            )

        # Build cache key based on scope
        scope = cor_record.get("rate_limit_scope") or "per_user"
        cache_key = self._build_cache_key(operation_name, scope, limit_type)

        # Atomic increment to avoid race conditions
        new_count = frappe.cache.incrby(cache_key, 1)

        # Set TTL on first request (when counter was just created)
        if new_count == 1:
            frappe.cache.expire(cache_key, period_seconds)

        allowed = new_count <= max_calls
        reason = "" if allowed else f"Rate limit exceeded: {new_count}/{max_calls}"

        return RateLimitResult(
            allowed=allowed,
            current_count=new_count,
            max_calls=max_calls,
            period_seconds=period_seconds,
            limit_type=limit_type,
            reason=reason,
        )

    def _get_cor_config(self, operation_name: str) -> Optional[Dict[str, Any]]:
        """
        Get Critical Operation Rule configuration for an operation.

        Args:
            operation_name: Name of the operation to get config for

        Returns:
            dict: COR configuration or None if not found
        """
        # Fields to fetch from COR
        fields = [
            "rate_limit_calls",
            "rate_limit_period_seconds",
            "rate_limit_scope",
            "batch_rate_limit_calls",
            "batch_rate_limit_period_seconds",
            "apply_batch_limits_to",
            "security_level",  # For rate limit enforcement in background context
        ]

        # Try to find specific COR record for this operation
        cor_record = frappe.db.get_value(
            "Critical Operation Rule",
            {"operation_name": operation_name, "enabled": 1},
            fields,
            as_dict=True,
        )

        # If no specific COR found, use generic fallback
        if not cor_record:
            cor_record = frappe.db.get_value(
                "Critical Operation Rule",
                {"operation_name": "_generic_api_fallback", "enabled": 1},
                fields,
                as_dict=True,
            )

        return cor_record

    def _detect_execution_context(self) -> ExecutionContext:
        """
        Detect the execution context to determine appropriate rate limiting.

        Returns:
            ExecutionContext: The detected execution context
        """
        # Check if we're in a background job context
        if getattr(frappe.flags, "in_background_job", False):
            return ExecutionContext.BACKGROUND_JOB

        # Check if we're in a scheduled task context
        if getattr(frappe.flags, "in_scheduler", False):
            return ExecutionContext.SCHEDULED_TASK

        # Check for async task markers
        if getattr(frappe.flags, "enqueue_after_commit", False):
            return ExecutionContext.BACKGROUND_JOB

        # Default to interactive HTTP request
        return ExecutionContext.INTERACTIVE

    def _get_effective_limits(
        self, cor_record: Dict[str, Any], context: ExecutionContext, operation_name: str
    ) -> tuple:
        """
        Determine effective rate limits based on context.

        Returns:
            Tuple of (max_calls, period_seconds, limit_type)
        """
        # Start with interactive limits as defaults
        _calls = cor_record.get("rate_limit_calls")
        max_calls = _calls if _calls is not None else 10
        _period = cor_record.get("rate_limit_period_seconds")
        period_seconds = _period if _period is not None else 3600
        limit_type = "interactive"

        # Use batch limits if in background/scheduled context
        if context in [ExecutionContext.BACKGROUND_JOB, ExecutionContext.SCHEDULED_TASK]:
            apply_to = cor_record.get("apply_batch_limits_to") or "Both"
            should_use_batch = (
                (apply_to == "Both")
                or (apply_to == "Background Jobs" and context == ExecutionContext.BACKGROUND_JOB)
                or (apply_to == "Scheduled Tasks" and context == ExecutionContext.SCHEDULED_TASK)
            )

            # Only use batch limits if they're actually configured
            batch_calls = cor_record.get("batch_rate_limit_calls")
            if should_use_batch and batch_calls:
                max_calls = batch_calls
                period_seconds = cor_record.get("batch_rate_limit_period_seconds") or period_seconds
                limit_type = "batch"
                frappe.logger("verenigingen.rate_limit").debug(
                    f"Using batch rate limits for {operation_name} in {context.value} context: "
                    f"{max_calls}/{period_seconds}s"
                )
            else:
                # Batch context but no batch limits configured
                # SECURITY FIX: For CRITICAL/HIGH operations, inherit interactive limits
                security_level = (cor_record.get("security_level") or "").lower()
                if security_level in ["critical", "high"]:
                    # Inherit interactive limits for security-sensitive operations
                    frappe.logger("verenigingen.rate_limit").warning(
                        f"No batch limits configured for {security_level.upper()} operation "
                        f"{operation_name} in {context.value} context. "
                        f"Inheriting interactive limits ({max_calls}/{period_seconds}s) for security."
                    )
                    limit_type = "batch_inherited"
                else:
                    # For MEDIUM/LOW operations, allow bypass in batch context
                    frappe.logger("verenigingen.rate_limit").debug(
                        f"No batch limits configured for {operation_name}, "
                        f"skipping rate limits for {context.value} context"
                    )
                    limit_type = "bypass"

        return max_calls, period_seconds, limit_type

    def _build_cache_key(self, operation_name: str, scope: str, limit_type: str) -> str:
        """
        Build cache key for rate limit counter.

        Args:
            operation_name: Name of the operation
            scope: Rate limit scope (global, per_ip, per_user)
            limit_type: Type of limit (interactive, batch, batch_inherited)

        Returns:
            Cache key string
        """
        if scope == "global":
            return f"cor_rate_limit:{limit_type}:{operation_name}"
        elif scope == "per_ip":
            client_ip = self._get_client_ip()
            return f"cor_rate_limit:{limit_type}:{operation_name}:{client_ip}"
        else:  # per_user (default)
            return f"cor_rate_limit:{limit_type}:{operation_name}:{frappe.session.user}"

    def _get_client_ip(self) -> str:
        """
        Get client IP address with trusted proxy support.

        Uses centralized client_ip module for consistent IP detection
        across all security components.
        """
        return get_client_ip()

    def get_rate_limit_headers(self, operation_key: str) -> Dict[str, str]:
        """
        Get rate limit headers for HTTP responses.

        Args:
            operation_key: Full operation key

        Returns:
            Dict with X-RateLimit-* headers
        """
        try:
            operation_name = operation_key.split(".")[-1] if "." in operation_key else operation_key

            cor_record = self._get_cor_config(operation_name)
            if not cor_record:
                return {}

            _calls = cor_record.get("rate_limit_calls")
            max_calls = _calls if _calls is not None else 10
            _period = cor_record.get("rate_limit_period_seconds")
            period_seconds = _period if _period is not None else 3600
            scope = cor_record.get("rate_limit_scope") or "per_user"

            # Build cache key (headers are for HTTP, use interactive limit_type)
            cache_key = self._build_cache_key(operation_name, scope, "interactive")

            # Get current usage without modifying it
            current_count = int(frappe.cache().get(cache_key) or 0)
            remaining = max(0, max_calls - current_count)

            # Calculate reset time
            import time

            reset_time = int(time.time() + period_seconds)

            return {
                "X-RateLimit-Limit": str(max_calls),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_time),
                "X-RateLimit-Window": str(period_seconds),
            }

        except Exception as e:
            frappe.log_error(f"Failed to get rate limit headers: {str(e)}", "Rate Limiting Headers")
            return {}


# Singleton instance for convenience
_rate_limit_engine: Optional[RateLimitEngine] = None


def get_rate_limit_engine() -> RateLimitEngine:
    """Get singleton RateLimitEngine instance."""
    global _rate_limit_engine
    if _rate_limit_engine is None:
        _rate_limit_engine = RateLimitEngine()
    return _rate_limit_engine
