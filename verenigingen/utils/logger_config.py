#!/usr/bin/env python3
"""
Logger Configuration for Verenigingen Security
===============================================

Ensures security logs are written to the correct file path.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

import frappe


def setup_security_logger():
    """
    Configure the security logger to write to the correct file.
    This ensures frappe.logger("verenigingen.security") writes to logs/verenigingen.security.log
    """
    # Get the logs directory path
    logs_dir = frappe.get_site_path("logs")

    # Ensure logs directory exists
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    # Define the security log file path
    security_log_path = os.path.join(logs_dir, "verenigingen.security.log")

    # Get or create the security logger
    security_logger = logging.getLogger("verenigingen.security")

    # Don't add handlers if they already exist
    if not security_logger.handlers:
        # Set logging level
        security_logger.setLevel(logging.INFO)

        # Create rotating file handler (10MB max, keep 5 backups)
        file_handler = RotatingFileHandler(
            security_log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10MB
        )

        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)

        # Add handler to logger
        security_logger.addHandler(file_handler)

        # Prevent propagation to avoid duplicate logs
        security_logger.propagate = False

    return security_logger


def get_security_logger():
    """
    Get the configured security logger.
    Ensures it's properly set up before returning.
    """
    setup_security_logger()
    return logging.getLogger("verenigingen.security")


def verify_logger_configuration():
    """
    Verify that the logger is correctly configured and can write to the file.
    Returns a dict with verification results.
    """
    try:
        # Set up the logger
        logger = setup_security_logger()

        # Get the log file path
        logs_dir = frappe.get_site_path("logs")
        security_log_path = os.path.join(logs_dir, "verenigingen.security.log")

        # Test write
        test_message = f"Logger verification test at {frappe.utils.now_datetime()}"
        logger.info(test_message)

        # Check if file exists and is writable
        file_exists = os.path.exists(security_log_path)
        file_writable = os.access(security_log_path, os.W_OK) if file_exists else False

        # Get file size
        file_size = os.path.getsize(security_log_path) if file_exists else 0

        return {
            "success": True,
            "log_path": security_log_path,
            "file_exists": file_exists,
            "file_writable": file_writable,
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "logger_name": "verenigingen.security",
            "handler_count": len(logger.handlers),
            "test_message_written": test_message,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "log_path": None}


@frappe.whitelist()
def get_security_log_info():
    """
    Get information about the security log file.
    Useful for monitoring and debugging.
    """
    # Check permissions
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw("Insufficient permissions", frappe.PermissionError)

    return verify_logger_configuration()


@frappe.whitelist()
def get_recent_security_logs(lines=50):
    """
    Get the most recent security log entries.

    Args:
        lines: Number of recent lines to return (max 100)
    """
    # Check permissions
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw("Insufficient permissions", frappe.PermissionError)

    try:
        # Limit lines to prevent excessive reads
        lines = min(int(lines), 100)

        # Get log file path
        logs_dir = frappe.get_site_path("logs")
        security_log_path = os.path.join(logs_dir, "verenigingen.security.log")

        if not os.path.exists(security_log_path):
            return {"success": False, "message": "Security log file not found", "logs": []}

        # Read last N lines efficiently
        with open(security_log_path, "rb") as f:
            # Go to end of file
            f.seek(0, 2)
            file_size = f.tell()

            # Read backwards to get last N lines
            block_size = min(file_size, 8192)
            blocks = []
            lines_found = 0

            while lines_found < lines and file_size > 0:
                # Read a block
                read_size = min(block_size, file_size)
                file_size -= read_size
                f.seek(file_size)
                block = f.read(read_size)
                blocks.insert(0, block)

                # Count lines in this block
                lines_found += block.count(b"\n")

            # Join blocks and decode
            all_data = b"".join(blocks).decode("utf-8", errors="ignore")

            # Get last N lines
            all_lines = all_data.splitlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

            return {
                "success": True,
                "log_path": security_log_path,
                "line_count": len(recent_lines),
                "logs": recent_lines,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "logs": []}


# Initialize logger when module is imported
setup_security_logger()
