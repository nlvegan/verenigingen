"""
Rate Limiting System for Verenigingen SEPA Operations

This module provides rate limiting functionality to prevent abuse of SEPA batch
operations and other sensitive endpoints. Supports both Redis and memory backends
with sliding window algorithm.
"""

import json
import time
from collections import defaultdict, deque
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cstr

from verenigingen.utils.error_handling import SEPAError, log_error
from verenigingen.utils.security.types import OperationType


class RateLimitExceeded(SEPAError):
    """Raised when rate limit is exceeded"""

    pass


class RateLimiter:
    """
    Rate limiting utility using sliding window algorithm

    Supports both Redis (production) and memory (development) backends
    """

    def __init__(self, backend="auto"):
        """
        Initialize rate limiter

        Args:
            backend: "redis", "memory", or "auto" (detect best available)
        """
        self.backend = self._detect_backend(backend)
        self._memory_store = defaultdict(lambda: deque())

    def _detect_backend(self, preference):
        """Detect best available backend"""
        if preference == "memory":
            return "memory"
        elif preference == "redis":
            if self._redis_available():
                return "redis"
            else:
                frappe.log_error(
                    "Redis not available, falling back to memory backend", "Rate Limiting Backend"
                )
                return "memory"
        else:  # auto
            return "redis" if self._redis_available() else "memory"

    def _redis_available(self):
        """Check if Redis is available"""
        try:
            import redis

            # Try to get Redis connection from Frappe
            redis_conn = frappe.cache()
            if redis_conn:
                redis_conn.ping()
                return True
        except:
            pass
        return False

    def _get_rate_limit_key(self, operation: str, user: str, ip: str = None):
        """Generate rate limit key"""
        # Include IP for additional protection
        ip_part = f":{ip}" if ip else ""
        return f"rate_limit:{operation}:{user}{ip_part}"

    def _check_redis_rate_limit(self, key: str, limit: int, window: int) -> Dict[str, Any]:
        """Check rate limit using Redis backend"""
        try:
            redis_conn = frappe.cache()
            current_time = time.time()

            # Use Redis pipeline for atomic operations
            pipe = redis_conn.pipeline()

            # Remove expired entries
            pipe.zremrangebyscore(key, 0, current_time - window)

            # Count current requests
            pipe.zcard(key)

            # Add current request
            pipe.zadd(key, {str(current_time): current_time})

            # Set expiry
            pipe.expire(key, window)

            results = pipe.execute()
            current_count = results[1]  # Count after cleanup

            # Check if limit exceeded
            if current_count >= limit:
                return {
                    "allowed": False,
                    "current_count": current_count,
                    "limit": limit,
                    "reset_time": current_time + window,
                    "retry_after": window,
                }

            return {
                "allowed": True,
                "current_count": current_count + 1,
                "limit": limit,
                "reset_time": current_time + window,
                "retry_after": 0,
            }

        except Exception as e:
            # Fallback to memory if Redis fails
            frappe.log_error(f"Redis rate limiting failed: {str(e)}", "Rate Limiting")
            return self._check_memory_rate_limit(key, limit, window)

    def _check_memory_rate_limit(self, key: str, limit: int, window: int) -> Dict[str, Any]:
        """Check rate limit using memory backend"""
        current_time = time.time()
        cutoff_time = current_time - window

        # Get request queue for this key
        request_queue = self._memory_store[key]

        # Remove expired entries
        while request_queue and request_queue[0] < cutoff_time:
            request_queue.popleft()

        current_count = len(request_queue)

        # Check if limit exceeded
        if current_count >= limit:
            return {
                "allowed": False,
                "current_count": current_count,
                "limit": limit,
                "reset_time": request_queue[0] + window if request_queue else current_time + window,
                "retry_after": window,
            }

        # Add current request
        request_queue.append(current_time)

        return {
            "allowed": True,
            "current_count": current_count + 1,
            "limit": limit,
            "reset_time": current_time + window,
            "retry_after": 0,
        }

    def _get_user_limit(self, operation: str, user: str) -> Tuple[int, int]:
        """
        Get rate limit and window for user and operation

        NOTE: SEPA rate limiter is deprecated. Rate limiting is now handled
        by the COR-based system in api_security_framework. This method provides
        backward compatibility for existing code.

        Args:
            operation: Operation type (e.g., "sepa_batch_creation")
            user: User email

        Returns:
            Tuple of (limit, window_seconds)
        """
        # Default conservative limits for backward compatibility
        # These are intentionally restrictive since this system is deprecated
        default_limits = {
            "sepa_batch_creation": (5, 300),  # 5 requests per 5 minutes
            "sepa_validation": (20, 60),  # 20 requests per minute
            "sepa_analytics": (30, 60),  # 30 requests per minute
            "sepa_loading": (15, 60),  # 15 requests per minute
        }

        # Get default limit for operation, or use very conservative fallback
        limit, window = default_limits.get(operation, (10, 300))  # 10 requests per 5 minutes

        # Apply role-based adjustments (more restrictive for regular users)
        user_roles = frappe.get_roles(user) if user else []

        if "System Manager" in user_roles:
            # System managers get higher limits
            limit = int(limit * 2)
        elif "Accounts Manager" in user_roles:
            # Accounts managers get moderate increase for financial operations
            if operation.startswith("sepa_"):
                limit = int(limit * 1.5)

        return limit, window

    def check_rate_limit(self, operation: str, user: str = None, ip: str = None) -> Dict[str, Any]:
        """
        Check if request is within rate limits

        Args:
            operation: Operation type (e.g., "sepa_batch_creation")
            user: User email (defaults to current user)
            ip: IP address (defaults to current request IP)

        Returns:
            Dictionary with rate limit status

        Raises:
            RateLimitExceeded: If rate limit is exceeded
        """
        if not user:
            user = frappe.session.user

        if not ip:
            ip = getattr(frappe.local, "request_ip", None)

        # Skip rate limiting for system users
        if user in ["Administrator", "System"]:
            return {
                "allowed": True,
                "current_count": 0,
                "limit": float("inf"),
                "window": 0,
                "reset_time": 0,
                "retry_after": 0,
            }

        # Skip rate limiting during test execution
        if getattr(frappe.flags, "in_test", False):
            return {
                "allowed": True,
                "current_count": 0,
                "limit": float("inf"),
                "window": 0,
                "reset_time": 0,
                "retry_after": 0,
            }

        # Get user-specific limits
        limit, window = self._get_user_limit(operation, user)
        key = self._get_rate_limit_key(operation, user, ip)

        # Check rate limit based on backend
        if self.backend == "redis":
            result = self._check_redis_rate_limit(key, limit, window)
        else:
            result = self._check_memory_rate_limit(key, limit, window)

        # Log rate limit check
        frappe.logger().info(
            {
                "event": "rate_limit_check",
                "operation": operation,
                "user": user,
                "ip": ip,
                "allowed": result["allowed"],
                "current_count": result["current_count"],
                "limit": result["limit"],
                "backend": self.backend,
            },
            "SEPA Security",
        )

        if not result["allowed"]:
            raise RateLimitExceeded(
                _("Rate limit exceeded for {0}. Limit: {1} requests per {2} seconds. Current: {3}").format(
                    operation, result["limit"], window, result["current_count"]
                )
            )

        return result

    def get_rate_limit_headers(self, operation: str, user: str = None) -> Dict[str, str]:
        """
        Get rate limit headers for HTTP responses

        Args:
            operation: Operation type
            user: User email (defaults to current user)

        Returns:
            Dictionary of HTTP headers
        """
        if not user:
            user = frappe.session.user

        limit, window = self._get_user_limit(operation, user)
        key = self._get_rate_limit_key(operation, user)

        try:
            # Get current count without incrementing
            if self.backend == "redis":
                redis_conn = frappe.cache()
                current_time = time.time()
                redis_conn.zremrangebyscore(key, 0, current_time - window)
                current_count = redis_conn.zcard(key)
                reset_time = current_time + window
            else:
                current_time = time.time()
                cutoff_time = current_time - window
                request_queue = self._memory_store[key]

                # Remove expired without modifying original
                valid_requests = [req for req in request_queue if req >= cutoff_time]
                current_count = len(valid_requests)
                reset_time = current_time + window

            return {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(max(0, limit - current_count)),
                "X-RateLimit-Reset": str(int(reset_time)),
                "X-RateLimit-Window": str(window),
            }

        except Exception as e:
            frappe.log_error(f"Failed to get rate limit headers: {str(e)}", "Rate Limiting")
            return {}


# Global rate limiter instance
_rate_limiter = None


def get_rate_limiter():
    """Get global rate limiter instance"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def rate_limit(operation: str):
    """
    Decorator to apply rate limiting to API endpoints

    Usage:
        @frappe.whitelist()
        @rate_limit("sepa_batch_creation")
        def create_sepa_batch():
            # Function implementation
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # Check rate limit
                limiter = get_rate_limiter()
                limiter.check_rate_limit(operation)

                # Add rate limit headers to response
                headers = limiter.get_rate_limit_headers(operation)
                if headers:
                    for header, value in headers.items():
                        frappe.local.response.setdefault("headers", {})[header] = value

                # Execute function
                return func(*args, **kwargs)

            except RateLimitExceeded as e:
                # Log rate limit violation
                log_error(
                    e,
                    context={
                        "function": func.__name__,
                        "operation": operation,
                        "user": frappe.session.user,
                        "ip": getattr(frappe.local, "request_ip", None),
                        "user_agent": frappe.get_request_header("User-Agent"),
                    },
                    module="verenigingen.utils.security.rate_limiting",
                )

                # Add rate limit headers even for blocked requests
                limiter = get_rate_limiter()
                headers = limiter.get_rate_limit_headers(operation)
                if headers:
                    for header, value in headers.items():
                        frappe.local.response.setdefault("headers", {})[header] = value

                frappe.throw(str(e), exc=frappe.ValidationError, title=_("Rate Limit Exceeded"))

        return wrapper

    return decorator


# API endpoints for rate limit management
@frappe.whitelist(allow_guest=False)
def get_rate_limit_status(operation: str = None):
    # Utility operation: Rate limit status retrieval
    """
    Get current rate limit status for user

    Args:
        operation: Specific operation to check (optional)

    Returns:
        Dictionary with rate limit status
    """
    try:
        limiter = get_rate_limiter()
        user = frappe.session.user

        if operation:
            # Get status for specific operation
            limit, window = limiter._get_user_limit(operation, user)
            headers = limiter.get_rate_limit_headers(operation, user)

            return {
                "success": True,
                "operation": operation,
                "limit": limit,
                "window_seconds": window,
                "remaining": int(headers.get("X-RateLimit-Remaining", 0)),
                "reset_time": int(headers.get("X-RateLimit-Reset", 0)),
                "headers": headers,
            }
        else:
            # SEPA rate limiter no longer maintains operation lists
            # Rate limiting is now handled by COR-based system in api_security_framework
            return {
                "success": False,
                "message": "SEPA rate limiter deprecated - use COR-based system via api_security_framework",
                "migration_note": "Rate limit status for all operations now available via Critical Operation Rules",
            }

    except Exception as e:
        log_error(
            e,
            context={"operation": operation, "user": frappe.session.user},
            module="verenigingen.utils.security.rate_limiting",
        )

        return {"success": False, "error": _("Failed to get rate limit status"), "message": str(e)}


@frappe.whitelist()
def clear_rate_limits(operation: str = None, user: str = None):
    # Development-only utility operation: Clear rate limits
    """
    Clear rate limits (admin only)

    Args:
        operation: Specific operation to clear (optional)
        user: Specific user to clear (optional)

    Returns:
        Dictionary with result
    """
    # Development-only check
    if not frappe.conf.developer_mode:
        frappe.throw(_("Rate limit clearing is only available in developer mode"), frappe.PermissionError)

    # Require admin permission
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can clear rate limits"), frappe.PermissionError)

    try:
        limiter = get_rate_limiter()

        if limiter.backend == "redis":
            redis_conn = frappe.cache()
            pattern = "rate_limit:"

            if operation:
                pattern += f"{operation}:"
            if user:
                pattern += f"*{user}*"
            else:
                pattern += "*"

            # Get and delete matching keys
            keys = redis_conn.keys(pattern)
            if keys:
                redis_conn.delete(*keys)
            cleared_count = len(keys)

        else:
            # Memory backend
            keys_to_clear = []
            for key in list(limiter._memory_store.keys()):
                if operation and operation not in key:
                    continue
                if user and user not in key:
                    continue
                keys_to_clear.append(key)

            for key in keys_to_clear:
                del limiter._memory_store[key]

            cleared_count = len(keys_to_clear)

        return {
            "success": True,
            "cleared_count": cleared_count,
            "message": _("Cleared {0} rate limit entries").format(cleared_count),
        }

    except Exception as e:
        log_error(
            e,
            context={"operation": operation, "user": user},
            module="verenigingen.utils.security.rate_limiting",
        )

        return {"success": False, "error": _("Failed to clear rate limits"), "message": str(e)}


def setup_rate_limiting():
    """
    Setup rate limiting during app initialization
    """
    # Initialize global rate limiter
    global _rate_limiter
    _rate_limiter = RateLimiter()

    # Log setup completion
    frappe.logger().info(
        {
            "event": "rate_limiting_setup_complete",
            "backend": _rate_limiter.backend,
            "timestamp": frappe.utils.now(),
        },
        "SEPA Security Setup",
    )
