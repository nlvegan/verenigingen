"""
Rate limiting utilities for security-sensitive operations
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import add_to_date, now_datetime


def check_approval_rate_limit(user, max_approvals=10, window_minutes=60):
    """
    Check if user has exceeded approval rate limit

    Args:
        user: User ID
        max_approvals: Maximum approvals allowed in time window
        window_minutes: Time window in minutes

    Returns:
        bool: True if within limits, False if exceeded
    """
    try:
        # Calculate time window
        window_start = add_to_date(now_datetime(), minutes=-window_minutes)

        # Count recent approval operations by this user
        recent_approvals = frappe.db.count(
            "Error Log",
            {"error": ["like", f"%User {user} attempting approval%"], "creation": [">=", window_start]},
        )

        # Also check for actual membership status changes (more accurate)
        recent_member_changes = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM `tabVersion`
            WHERE ref_doctype = 'Member'
            AND owner = %s
            AND creation >= %s
            AND data LIKE '%application_status%'
        """,
            (user, window_start),
            as_dict=True,
        )

        total_operations = recent_approvals + (recent_member_changes[0].count if recent_member_changes else 0)

        return total_operations < max_approvals

    except Exception as e:
        # If rate limiting fails, err on the side of caution but don't block operations
        frappe.log_error(f"Rate limiting check failed for user {user}: {str(e)}")
        return True  # Allow operation but log the issue


def check_api_rate_limit(user, endpoint, max_requests=100, window_minutes=60):
    """
    General API rate limiting for any endpoint

    Args:
        user: User ID
        endpoint: API endpoint name
        max_requests: Maximum requests allowed in time window
        window_minutes: Time window in minutes

    Returns:
        bool: True if within limits, False if exceeded
    """
    try:
        # Use frappe cache for rate limiting
        cache_key = f"rate_limit:{user}:{endpoint}"
        window_start = now_datetime() - timedelta(minutes=window_minutes)

        # Get or initialize request log
        request_log = frappe.cache().get(cache_key) or []

        # Filter to current window
        current_requests = [
            req_time for req_time in request_log if datetime.fromisoformat(req_time) > window_start
        ]

        # Check if limit exceeded
        if len(current_requests) >= max_requests:
            return False

        # Add current request
        current_requests.append(now_datetime().isoformat())

        # Store back in cache (expire after window duration)
        frappe.cache().set(cache_key, current_requests, expire=window_minutes * 60)

        return True

    except Exception as e:
        frappe.log_error(f"API rate limiting failed for user {user}, endpoint {endpoint}: {str(e)}")
        return True  # Allow operation but log the issue


def log_security_event(user, event_type, details, severity="medium"):
    """
    Log security-relevant events for monitoring

    Args:
        user: User ID
        event_type: Type of security event
        details: Event details
        severity: Event severity (low, medium, high, critical)
    """
    try:
        # Create security log entry
        security_log = frappe.get_doc(
            {
                "doctype": "Error Log",
                "method": f"Security Event: {event_type}",
                "error": f"User: {user}\nSeverity: {severity}\nDetails: {details}",
                "creation": now_datetime(),
            }
        )
        security_log.insert(ignore_permissions=True)

        # For high/critical events, also create system alert
        if severity in ["high", "critical"]:
            try:
                alert = frappe.get_doc(
                    {
                        "doctype": "System Alert",
                        "alert_type": "Security",
                        "message": f"Security Event: {event_type} by user {user}",
                        "details": details,
                        "severity": severity.capitalize(),
                        "status": "Open",
                    }
                )
                alert.insert(ignore_permissions=True)
                frappe.db.commit()
            except Exception:
                pass  # Don't fail main operation if alert creation fails

    except Exception as e:
        # Even if logging fails, don't interrupt the main operation
        print(f"Failed to log security event: {str(e)}")


def validate_input_security(data, field_name, max_length=1000, allow_html=False):
    """
    Validate and sanitize user inputs for security

    Args:
        data: Input data to validate
        field_name: Name of the field being validated
        max_length: Maximum allowed length
        allow_html: Whether to allow HTML content

    Returns:
        str: Sanitized input data

    Raises:
        frappe.ValidationError: If input fails validation
    """
    if not data:
        return data

    # Convert to string
    data = str(data)

    # Length check
    if len(data) > max_length:
        frappe.throw(f"{field_name} exceeds maximum length of {max_length} characters")

    # Basic XSS prevention
    if not allow_html:
        # Remove potentially dangerous HTML tags and attributes
        import re

        # Remove script tags
        data = re.sub(r"<script[^>]*?>.*?</script>", "", data, flags=re.IGNORECASE | re.DOTALL)

        # Remove common XSS vectors
        dangerous_patterns = [
            r"javascript:",
            r"on\w+\s*=",  # Event handlers like onclick, onload
            r"<iframe",
            r"<object",
            r"<embed",
            r"<form",
        ]

        for pattern in dangerous_patterns:
            data = re.sub(pattern, "", data, flags=re.IGNORECASE)

    # SQL injection prevention (basic)
    sql_patterns = [
        r";\s*(drop|delete|truncate|alter|create)\s+",
        r"union\s+select",
        r"<script",
        r"exec\s*\(",
    ]

    for pattern in sql_patterns:
        if re.search(pattern, data, re.IGNORECASE):
            frappe.throw(f"Invalid characters detected in {field_name}")

    return data


def check_concurrent_operations(user, operation_type, max_concurrent=3):
    """
    Check for concurrent operations to prevent race conditions

    Args:
        user: User ID
        operation_type: Type of operation (e.g., "membership_approval")
        max_concurrent: Maximum concurrent operations allowed

    Returns:
        bool: True if operation can proceed, False otherwise
    """
    try:
        cache_key = f"concurrent_ops:{user}:{operation_type}"
        current_ops = frappe.cache().get(cache_key) or 0

        if current_ops >= max_concurrent:
            return False

        # Increment counter (expire after 5 minutes)
        frappe.cache().set(cache_key, current_ops + 1, expire=300)

        return True

    except Exception as e:
        frappe.log_error(f"Concurrent operation check failed: {str(e)}")
        return True  # Allow operation if check fails
