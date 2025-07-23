"""
Simple performance monitoring utilities
"""

import functools
import time

import frappe


def monitor_performance(func):
    """
    Simple performance monitoring decorator
    Logs slow function execution for optimization purposes
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            execution_time = time.time() - start_time
            # Log if execution takes longer than 1 second
            if execution_time > 1.0:
                frappe.logger().info(f"Slow function detected: {func.__name__} took {execution_time:.2f}s")

    return wrapper
