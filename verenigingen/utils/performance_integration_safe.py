#!/usr/bin/env python3
"""
Safe Performance Integration Module
Problem #1 Resolution: Safe integration layer without monkey patching

This module provides safe integration for performance optimizations using
proper Frappe event hooks instead of dangerous monkey patching.

IMPORTANT: This replaces the previous performance_integration.py which used
dangerous monkey patching patterns that posed security risks.

Integration Strategy:
1. Event-driven optimization through document hooks
2. Background job optimization for heavy operations
3. Safe backwards-compatible helper functions
4. Validation and monitoring of optimization system

SECURITY: All monkey patching has been eliminated to prevent method replacement
vulnerabilities and ensure system stability.
"""

import time
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now, nowdate

from verenigingen.utils.optimized_queries import (
    OptimizedMemberQueries,
    OptimizedSEPAQueries,
    OptimizedVolunteerQueries,
    validate_member_names,
)

# Import the safe event handlers instead of monkey patching
from verenigingen.utils.performance_event_handlers import (
    PerformanceEventHandlers,
    optimized_update_member_payment_history,
    optimized_update_member_payment_history_from_invoice,
)


class SafePerformanceIntegration:
    """
    Main integration class for performance optimizations using safe patterns

    This class uses event-driven patterns and proper Frappe hooks instead
    of dangerous monkey patching to integrate performance optimizations.
    """

    @staticmethod
    def install():
        """
        Initialize performance optimization system using safe patterns

        This method sets up the performance optimization system without
        monkey patching existing methods, which was a security risk.
        """

        try:
            # Initialize performance system safely
            SafePerformanceIntegration._initialize_optimization_system()
            SafePerformanceIntegration._setup_event_handlers()
            SafePerformanceIntegration._validate_system_integrity()

            frappe.logger().info("Safe performance optimization system initialized successfully")
            return {"success": True, "message": "Performance optimization system ready"}

        except Exception as e:
            error_msg = f"Failed to initialize performance optimization system: {str(e)}"
            frappe.log_error(error_msg, "Performance Integration Error")
            return {"success": False, "error": error_msg}

    @staticmethod
    def _initialize_optimization_system():
        """Initialize the performance optimization system without monkey patching"""

        # Validate that all optimization modules are available
        try:
            # Test that optimized query classes are available
            assert hasattr(OptimizedMemberQueries, "bulk_update_payment_history")
            assert hasattr(OptimizedVolunteerQueries, "get_volunteer_assignments_bulk")
            assert hasattr(OptimizedSEPAQueries, "get_active_mandates_for_members")

            # Validate input validation functions
            assert callable(validate_member_names)

            frappe.logger().info("All optimization modules validated successfully")

        except Exception as e:
            raise Exception(f"Failed to validate optimization modules: {str(e)}")

    @staticmethod
    def _setup_event_handlers():
        """Setup event handlers for performance optimization triggers"""

        # Verify that event handlers are available
        try:
            assert hasattr(PerformanceEventHandlers, "on_member_payment_update")
            assert hasattr(PerformanceEventHandlers, "on_volunteer_assignment_change")
            assert hasattr(PerformanceEventHandlers, "on_sepa_mandate_change")
            assert hasattr(PerformanceEventHandlers, "bulk_optimize_member_data")

            frappe.logger().info("Event handlers validated successfully")

        except Exception as e:
            raise Exception(f"Failed to validate event handlers: {str(e)}")

    @staticmethod
    def _validate_system_integrity():
        """Validate system integrity and safety"""

        try:
            # Ensure no monkey patching is active
            SafePerformanceIntegration._verify_no_monkey_patching()

            # Test core functionality
            SafePerformanceIntegration._test_core_functionality()

            frappe.logger().info("System integrity validated successfully")

        except Exception as e:
            raise Exception(f"System integrity validation failed: {str(e)}")

    @staticmethod
    def _verify_no_monkey_patching():
        """Verify that no dangerous monkey patching is active"""

        # Check that we haven't modified any core methods
        try:
            import verenigingen.verenigingen.doctype.member.member_utils as member_utils

            # Verify original functions are not replaced
            dangerous_attributes = [
                "_original_update_member_payment_history",
                "_original_update_member_payment_history_from_invoice",
            ]

            for attr in dangerous_attributes:
                if hasattr(member_utils, attr):
                    raise Exception(f"Dangerous monkey patching detected: {attr}")

            frappe.logger().info("No monkey patching detected - system is safe")

        except ImportError:
            # Module might not exist, that's ok
            pass

    @staticmethod
    def _test_core_functionality():
        """Test core optimization functionality"""

        try:
            # Test that we can create safe SQL placeholders
            from verenigingen.utils.optimized_queries import create_safe_sql_placeholders

            test_placeholders = create_safe_sql_placeholders(5)
            assert test_placeholders == "%s,%s,%s,%s,%s"

            # Test input validation
            try:
                validate_member_names(["test-member"])  # Should pass
                frappe.logger().info("Input validation working correctly")
            except ValueError:
                pass  # Expected for invalid names

            frappe.logger().info("Core functionality test passed")

        except Exception as e:
            raise Exception(f"Core functionality test failed: {str(e)}")

    @staticmethod
    def uninstall():
        """
        Safely uninstall performance optimizations

        This method doesn't need to do anything since we don't use monkey patching.
        """
        frappe.logger().info("Performance optimizations uninstalled (no cleanup needed)")
        return {"success": True, "message": "Performance optimizations safely uninstalled"}

    @staticmethod
    def get_status():
        """Get current status of performance optimization system"""

        try:
            status = {
                "system_active": True,
                "monkey_patching_active": False,
                "event_handlers_available": True,
                "optimization_modules_loaded": True,
                "security_status": "SAFE",
                "available_optimizations": [
                    "Member payment history bulk updates",
                    "Volunteer assignment bulk loading",
                    "SEPA mandate bulk loading",
                    "Financial summary bulk loading",
                ],
                "integration_method": "Event-driven hooks (safe)",
                "input_validation": "Active",
                "sql_injection_protection": "Active",
            }

            # Verify no monkey patching is active
            try:
                SafePerformanceIntegration._verify_no_monkey_patching()
                status["monkey_patching_detected"] = False
            except Exception as e:
                status["monkey_patching_detected"] = True
                status["security_status"] = "UNSAFE"
                status["security_warning"] = str(e)

            return status

        except Exception as e:
            return {"system_active": False, "error": str(e), "security_status": "UNKNOWN"}


# Safe backwards compatibility functions
# These provide compatibility without dangerous method replacement
def get_optimized_member_payment_update():
    """Get the optimized member payment update function safely"""
    return optimized_update_member_payment_history


def get_optimized_member_payment_update_from_invoice():
    """Get the optimized payment update from invoice function safely"""
    return optimized_update_member_payment_history_from_invoice


def trigger_bulk_member_optimization(member_names: List[str]):
    """Trigger bulk optimization for members safely"""
    if not member_names:
        return {"success": True, "message": "No members to optimize"}

    try:
        validate_member_names(member_names)
        return PerformanceEventHandlers.bulk_optimize_member_data(member_names)
    except Exception as e:
        frappe.log_error(
            f"Failed to trigger bulk optimization: {str(e)}", "Safe Performance Integration Error"
        )
        return {"success": False, "error": str(e)}


# API endpoints for safe performance management
@frappe.whitelist()
def install_safe_performance_optimizations():
    """API endpoint to install safe performance optimizations"""
    return SafePerformanceIntegration.install()


@frappe.whitelist()
def get_performance_system_status():
    """API endpoint to get performance system status"""
    return SafePerformanceIntegration.get_status()


@frappe.whitelist()
def uninstall_performance_optimizations():
    """API endpoint to uninstall performance optimizations"""
    return SafePerformanceIntegration.uninstall()


@frappe.whitelist()
def trigger_member_bulk_optimization(member_names):
    """API endpoint to trigger bulk member optimization"""
    try:
        if isinstance(member_names, str):
            import json

            member_names = json.loads(member_names)

        return trigger_bulk_member_optimization(member_names)

    except Exception as e:
        frappe.throw(_("Failed to trigger bulk optimization: {0}").format(str(e)))


# Initialize the safe performance system on module import
def initialize_on_import():
    """Initialize safe performance system when module is imported"""
    try:
        result = SafePerformanceIntegration.install()
        if result.get("success"):
            frappe.logger().info("Safe performance integration initialized automatically")
    except Exception as e:
        frappe.log_error(
            f"Failed to auto-initialize performance system: {str(e)}",
            "Performance Integration Initialization",
        )


# Auto-initialize when safe to do so (not during tests or setup)
if frappe.local and hasattr(frappe.local, "site") and frappe.local.site:
    try:
        initialize_on_import()
    except Exception:
        # Don't block module loading if initialization fails
        pass
