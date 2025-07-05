"""
Monkey patches for disabling certain functionality during tests.
"""
from contextlib import contextmanager

import frappe


def is_test_environment():
    """Check if we're running in a test environment."""
    # Check multiple indicators of test environment
    return (
        frappe.flags.in_test
        or frappe.conf.get("run_tests")
        or hasattr(frappe.local, "test_objects")
        or getattr(frappe.local, "in_test", False)
    )


def patch_sepa_notifications():
    """Disable SEPA mandate notifications during tests."""
    if not is_test_environment():
        return

    try:
        # Import the notification manager module
        from verenigingen.utils.sepa_notifications import SEPAMandateNotificationManager

        # List of all notification methods to patch
        notification_methods = [
            "send_mandate_created_notification",
            "send_mandate_cancelled_notification",
            "send_mandate_expiring_notification",
            "send_payment_retry_notification",
            "send_payment_success_notification",
            "send_pre_notification",
            "_send_email",  # Patch the underlying email method to catch all notifications
        ]

        def create_mock_method(method_name):
            """Create a mock method for the given method name"""

            def mock_method(self, *args, **kwargs):
                """Mock method that does nothing during tests."""
                frappe.logger().debug(f"SEPA notification disabled in test environment: {method_name} called")
                return None

            return mock_method

        # Patch all notification methods
        for method_name in notification_methods:
            if hasattr(SEPAMandateNotificationManager, method_name):
                # Store original method
                original_method = getattr(SEPAMandateNotificationManager, method_name)
                setattr(SEPAMandateNotificationManager, f"_original_{method_name}", original_method)

                # Apply mock method
                setattr(SEPAMandateNotificationManager, method_name, create_mock_method(method_name))

        frappe.logger().info("SEPA notifications patched for test environment")

    except ImportError as e:
        frappe.logger().warning(f"Could not import SEPA notification manager for patching: {e}")
    except Exception as e:
        frappe.logger().error(f"Error patching SEPA notifications: {e}")


def unpatch_sepa_notifications():
    """Restore original SEPA notification functionality."""
    try:
        from verenigingen.utils.sepa_notifications import SEPAMandateNotificationManager

        # List of all notification methods that were patched
        notification_methods = [
            "send_mandate_created_notification",
            "send_mandate_cancelled_notification",
            "send_mandate_expiring_notification",
            "send_payment_retry_notification",
            "send_payment_success_notification",
            "send_pre_notification",
            "_send_email",
        ]

        # Restore all original methods
        for method_name in notification_methods:
            original_attr_name = f"_original_{method_name}"
            if hasattr(SEPAMandateNotificationManager, original_attr_name):
                # Restore original method
                setattr(
                    SEPAMandateNotificationManager,
                    method_name,
                    getattr(SEPAMandateNotificationManager, original_attr_name),
                )
                # Remove the backup attribute
                delattr(SEPAMandateNotificationManager, original_attr_name)

        frappe.logger().info("SEPA notifications unpatched")

    except ImportError:
        pass
    except Exception as e:
        frappe.logger().error(f"Error unpatching SEPA notifications: {e}")


def apply_test_patches():
    """Apply all test patches. Call this in test setup."""
    if is_test_environment():
        patch_sepa_notifications()
        # Add more patches here as needed


def remove_test_patches():
    """Remove all test patches. Call this in test teardown."""
    unpatch_sepa_notifications()
    # Remove more patches here as needed


@contextmanager
def patched_tests():
    """Context manager for applying test patches.

    Usage:
        with patched_tests():
            # Your test code here
            pass
    """
    apply_test_patches()
    try:
        yield
    finally:
        remove_test_patches()
