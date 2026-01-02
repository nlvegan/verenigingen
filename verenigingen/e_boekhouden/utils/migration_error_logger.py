# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Migration Error Logger

Centralized error logging utilities for E-Boekhouden migrations.
Provides consistent error tracking, debug file creation, and failed records logging.
"""

import json
import os
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

import frappe


class MigrationErrorLogger:
    """
    Centralized error logging for E-Boekhouden migrations.

    Provides:
    - Enhanced error logging to Frappe Error Log
    - Debug file creation for immediate analysis
    - Failed records JSON logging for post-migration review
    """

    def __init__(self, migration_name: str, migration_doc_name: str):
        """
        Initialize the error logger.

        Args:
            migration_name: Human-readable migration identifier
            migration_doc_name: DocType document name for file naming
        """
        self.migration_name = migration_name
        self.migration_doc_name = migration_doc_name
        self.error_details = ""
        self.failed_record_details: List[Dict[str, Any]] = []

    def log_error(
        self, message: str, record_type: Optional[str] = None, record_data: Optional[Dict] = None
    ) -> str:
        """
        Enhanced error logging with detailed debugging information.

        Args:
            message: Error message
            record_type: Type of record that failed (e.g., 'account', 'transaction')
            record_data: Data of the failed record for debugging

        Returns:
            The enhanced error message that was logged
        """
        # Create a short title for the error log
        if record_type:
            title = f"E-Boekhouden {record_type} Error"
        else:
            # Extract first part of message for title
            title = message.split(":")[0] if ":" in message else message
            title = title[:100]

        # Ensure title is within 140 character limit
        if len(title) > 140:
            title = title[:137] + "..."

        # Enhanced error logging with full details
        enhanced_message = f"MIGRATION ERROR: {message}"

        # Add record data context if available
        if record_data:
            enhanced_message += f"\n\nRECORD DATA:\n{json.dumps(record_data, indent=2, default=str)}"

        # Add stack trace for debugging
        try:
            enhanced_message += f"\n\nSTACK TRACE:\n{traceback.format_exc()}"
        except Exception:
            pass

        # Add additional context
        enhanced_message += "\n\nCONTEXT:"
        enhanced_message += f"\n- Migration: {self.migration_name}"
        enhanced_message += f"\n- Timestamp: {frappe.utils.now_datetime()}"
        enhanced_message += f"\n- Record Type: {record_type or 'Unknown'}"

        # Log to Frappe Error Log
        try:
            frappe.log_error(enhanced_message, title)
        except Exception:
            try:
                frappe.log_error(enhanced_message, "E-Boekhouden Migration Error")
            except Exception:
                frappe.logger().error(f"E-Boekhouden Migration: {enhanced_message}")

        # Also save to debug file immediately
        self.save_debug_error(message, record_type, record_data, enhanced_message)

        # Track error details
        self.error_details += f"\n{message}" if self.error_details else message

        # Track failed record details if provided
        if record_type and record_data:
            self.failed_record_details.append(
                {
                    "timestamp": str(frappe.utils.now_datetime()),
                    "record_type": record_type,
                    "error_message": message,
                    "record_data": record_data,
                    "enhanced_message": enhanced_message,
                }
            )

        return enhanced_message

    def save_debug_error(
        self, message: str, record_type: Optional[str], record_data: Optional[Dict], enhanced_message: str
    ) -> Optional[str]:
        """
        Save error immediately to debug file for analysis.

        Args:
            message: Original error message
            record_type: Type of record
            record_data: Record data
            enhanced_message: Enhanced message with context

        Returns:
            Filepath where debug error was saved, or None if failed
        """
        try:
            # Create logs directory if it doesn't exist
            log_dir = frappe.get_site_path("private", "files", "eboekhouden_debug_logs")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # Create debug filename
            timestamp = datetime.now().strftime("%Y%m%d")
            filename = f"debug_errors_{self.migration_doc_name}_{timestamp}.txt"
            filepath = os.path.join(log_dir, filename)

            # Append error to debug file
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"ERROR TIMESTAMP: {frappe.utils.now_datetime()}\n")
                f.write(f"RECORD TYPE: {record_type or 'Unknown'}\n")
                f.write(f"{'=' * 80}\n")
                f.write(enhanced_message)
                f.write(f"\n{'=' * 80}\n\n")

            return filepath

        except Exception as e:
            frappe.logger().error(f"Failed to save debug error: {str(e)}")
            return None

    def save_failed_records_log(
        self, failed_records_count: int, additional_context: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Save detailed log of failed records to a JSON file.

        Args:
            failed_records_count: Total number of failed records
            additional_context: Optional additional context to include

        Returns:
            Filename where log was saved, or None if failed
        """
        try:
            # Create logs directory if it doesn't exist
            log_dir = frappe.get_site_path("private", "files", "eboekhouden_migration_logs")
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"failed_records_{self.migration_doc_name}_{timestamp}.json"
            filepath = os.path.join(log_dir, filename)

            # Build log data
            log_data = {
                "migration_name": self.migration_doc_name,
                "migration_id": self.migration_name,
                "timestamp": str(frappe.utils.now_datetime()),
                "total_failed": failed_records_count,
                "failed_records": self.failed_record_details,
            }

            if additional_context:
                log_data["additional_context"] = additional_context

            # Save the failed records
            with open(filepath, "w") as f:
                json.dump(log_data, f, indent=2, default=str)

            frappe.logger().info(f"Failed records log saved to: {filepath}")
            return filename

        except Exception as e:
            frappe.log_error(f"Failed to save failed records log: {str(e)}")
            return None

    def get_error_summary(self) -> str:
        """Get accumulated error details as a summary string."""
        return self.error_details

    def get_failed_records(self) -> List[Dict[str, Any]]:
        """Get list of failed record details."""
        return self.failed_record_details

    def clear(self):
        """Clear accumulated errors and failed records."""
        self.error_details = ""
        self.failed_record_details = []
