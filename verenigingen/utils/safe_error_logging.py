#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe Error Logging Utility
==========================

Prevents cascading error log failures due to character length limits
by intelligently truncating error messages while preserving key information.

Usage:
    from verenigingen.utils.safe_error_logging import safe_log_error

    safe_log_error("Operation failed", error_message)
"""

import frappe


def safe_log_error(title, message, max_title_length=100):
    """
    Safely log error without causing character length exceeded cascading failures.

    Args:
        title (str): Error title
        message (str): Error message
        max_title_length (int): Maximum title length to prevent truncation errors

    Returns:
        str: Error log name if successful, None if failed
    """
    try:
        # Truncate title if too long, leaving room for system additions
        safe_title = title[:max_title_length] if len(title) > max_title_length else title

        # Truncate message if extremely long to prevent issues
        max_message_length = 5000  # Reasonable limit for error messages
        safe_message = message[:max_message_length] if len(message) > max_message_length else message

        # If message was truncated, add indicator
        if len(message) > max_message_length:
            safe_message += f"\n\n[MESSAGE TRUNCATED - Original length: {len(message)} characters]"

        return frappe.log_error(safe_message, safe_title)

    except Exception as e:
        # Last resort: log a minimal error message
        try:
            minimal_title = f"Error logging failed: {title[:50]}"
            minimal_message = (
                f"Original error logging failed: {str(e)[:200]}\n\nOriginal message preview: {message[:500]}"
            )
            return frappe.log_error(minimal_message, minimal_title)
        except Exception:
            # If even minimal logging fails, just continue - don't crash the application
            frappe.logger().error(f"Complete error logging failure for: {title[:100]}")
            return None


def safe_log_error_context(operation_name, context_data, error):
    """
    Safely log error with context information for debugging.

    Args:
        operation_name (str): Name of the operation that failed
        context_data (dict): Relevant context data
        error (Exception): The error that occurred
    """
    try:
        # Build context summary
        context_summary = []
        if isinstance(context_data, dict):
            for key, value in list(context_data.items())[:10]:  # Limit to first 10 items
                context_summary.append(f"{key}: {str(value)[:100]}")
        else:
            context_summary.append(f"Context: {str(context_data)[:200]}")

        context_str = "\n".join(context_summary)

        message = f"""Operation: {operation_name}
Error: {str(error)}
Error Type: {type(error).__name__}

Context:
{context_str}
"""

        title = f"{operation_name} failed"
        return safe_log_error(title, message)

    except Exception:
        # Fallback to basic logging
        return safe_log_error(f"{operation_name} error", str(error))
