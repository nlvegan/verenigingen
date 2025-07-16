"""
Fix for cascading error log titles

Prevents error titles from becoming too long by truncating intelligently
"""

import frappe


def log_error_safely(message, title, max_title_length=140):
    """
    Log error with title truncation to prevent cascading title length errors

    Args:
        message: The error message (can be long)
        title: The error title (will be truncated if needed)
        max_title_length: Maximum allowed title length (default 140)
    """

    # Clean up the title
    if isinstance(title, Exception):
        title = str(title)

    # Remove nested error log references from title
    if "Error Log" in title:
        # Extract the core error message
        import re

        # Find the first actual error message
        match = re.search(r"Error[^:]*: ([^(]+)", title)
        if match:
            title = match.group(1).strip()
        else:
            # Just take the first part before "Error Log"
            title = title.split("Error Log")[0].strip()

    # Truncate title if too long
    if len(title) > max_title_length - 10:  # Leave some buffer
        title = title[: max_title_length - 13] + "..."

    # Ensure title is not empty
    if not title:
        title = "E-Boekhouden Migration Error"

    # Log the error
    try:
        frappe.log_error(title=title, message=message)
    except Exception:
        # If even this fails, use a minimal title
        frappe.log_error(title="Migration Error", message=f"Original Title: {title[:50]}...\n\n{message}")


def get_clean_error_message(e):
    """
    Extract clean error message from exception
    """
    error_str = str(e)

    # Handle IntegrityError specially
    if "IntegrityError" in error_str:
        if "Duplicate entry" in error_str:
            import re

            match = re.search(r"Duplicate entry '([^']+)'", error_str)
            if match:
                return f"Duplicate entry: {match.group(1)}"

    # Handle nested error logs
    if "Error Log" in error_str:
        # Extract the original error
        parts = error_str.split(":")
        for part in parts:
            if "Error Log" not in part and len(part.strip()) > 5:
                return part.strip()

    # Default - return first 200 chars
    return error_str[:200]


class SafeErrorLogger:
    """
    Context manager for safe error logging without cascading titles
    """

    def __init__(self, operation_name):
        self.operation_name = operation_name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            # Log the error safely
            clean_message = get_clean_error_message(exc_val)
            full_traceback = frappe.get_traceback()

            log_error_safely(message=full_traceback, title=f"{self.operation_name}: {clean_message}")

        # Don't suppress the exception
        return False

    def log_error(self, error, context=""):
        """Log error within the context"""
        clean_message = get_clean_error_message(error)

        title = self.operation_name
        if context:
            title += f" - {context}"
        title += f": {clean_message}"

        log_error_safely(message=f"{context}\n\n{str(error)}\n\n{frappe.get_traceback()}", title=title)
