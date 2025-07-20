#!/usr/bin/env python3
"""
Test script for Volunteer doctype concurrency and performance fixes
"""

import threading
import time

import frappe
from frappe.utils import random_string


def test_volunteer_query_optimization():
    """Test that optimized volunteer queries work correctly"""
    print("Testing Volunteer query optimization...")

    try:
        # Get a sample volunteer
        volunteers = frappe.get_all("Volunteer", limit=1)
        if not volunteers:
            print("No volunteers found to test with")
            return True

        volunteer_doc = frappe.get_doc("Volunteer", volunteers[0].name)

        # Test optimized assignments query
        start_time = time.time()
        assignments_optimized = volunteer_doc.get_aggregated_assignments_optimized()
        optimized_time = time.time() - start_time

        # Test fallback query
        start_time = time.time()
        assignments_fallback = volunteer_doc.get_aggregated_assignments_fallback()
        fallback_time = time.time() - start_time

        print(f"✅ Optimized assignments query: {optimized_time:.4f}s, Fallback query: {fallback_time:.4f}s")
        print(
            f"Optimized assignments: {len(assignments_optimized)}, Fallback assignments: {len(assignments_fallback)}"
        )

        # Test optimized history query
        start_time = time.time()
        history_optimized = volunteer_doc.get_volunteer_history_optimized()
        optimized_history_time = time.time() - start_time

        # Test fallback history query
        start_time = time.time()
        history_fallback = volunteer_doc.get_volunteer_history_fallback()
        fallback_history_time = time.time() - start_time

        print(
            f"✅ Optimized history query: {optimized_history_time:.4f}s, Fallback history query: {fallback_history_time:.4f}s"
        )
        print(f"Optimized history: {len(history_optimized)}, Fallback history: {len(history_fallback)}")

        # Test status update optimization
        start_time = time.time()
        has_assignments = volunteer_doc.has_active_assignments_optimized()
        status_time = time.time() - start_time

        print(f"✅ Status check optimization: {status_time:.4f}s, Has assignments: {has_assignments}")

        return True

    except Exception as e:
        print(f"❌ Volunteer query optimization test failed: {str(e)}")
        return False


def test_volunteer_concurrency():
    """Test volunteer operations under concurrent access"""
    print("\nTesting Volunteer concurrency handling...")

    operations_completed = []
    errors = []

    def volunteer_operation():
        try:
            # Get a volunteer
            volunteers = frappe.get_all("Volunteer", limit=1)
            if not volunteers:
                return

            volunteer_doc = frappe.get_doc("Volunteer", volunteers[0].name)

            # Perform concurrent operations
            assignments = volunteer_doc.get_aggregated_assignments()
            history = volunteer_doc.get_volunteer_history()

            operations_completed.append(f"Thread-{threading.current_thread().ident}")

        except Exception as e:
            errors.append(str(e))

    # Create multiple threads to test concurrency
    threads = []
    for i in range(5):
        thread = threading.Thread(target=volunteer_operation)
        threads.append(thread)

    # Start all threads
    for thread in threads:
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Check results
    print(f"Completed operations: {len(operations_completed)}")
    print(f"Errors: {len(errors)}")

    if errors:
        print(f"❌ Concurrency errors: {errors}")
        return False
    else:
        print("✅ All concurrent operations completed successfully")
        return True


def test_volunteer_activity_management():
    """Test volunteer activity addition and management"""
    print("\nTesting Volunteer activity management...")

    try:
        # Get or create a test volunteer
        test_volunteers = frappe.get_all("Volunteer", filters={"volunteer_name": ["like", "Test%"]}, limit=1)

        if test_volunteers:
            volunteer_doc = frappe.get_doc("Volunteer", test_volunteers[0].name)
        else:
            # Create a test volunteer
            volunteer_doc = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"Test Volunteer {random_string(5)}",
                    "email": f"test.volunteer.{random_string(5)}@example.com",
                    "status": "Active"}
            )
            volunteer_doc.insert(ignore_permissions=True)

        # Test adding an activity
        activity_name = volunteer_doc.add_activity(
            activity_type="Project",
            role="Coordinator",
            description="Test project coordination",
            estimated_hours=10,
            notes="Performance test activity",
        )

        print(f"✅ Activity created: {activity_name}")

        # Test ending the activity
        result = volunteer_doc.end_activity(
            activity_name=activity_name, notes="Activity completed for testing"
        )

        print(f"✅ Activity ended successfully: {result}")

        # Clean up test data
        if activity_name:
            try:
                frappe.delete_doc("Volunteer Activity", activity_name, ignore_permissions=True)
            except:
                pass  # Ignore cleanup errors

        return True

    except Exception as e:
        print(f"❌ Volunteer activity management test failed: {str(e)}")
        return False


def test_volunteer_performance_edge_cases():
    """Test performance under edge case scenarios"""
    print("\nTesting Volunteer performance edge cases...")

    try:
        # Test with volunteer with no assignments
        volunteer_doc = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Empty Test Volunteer {random_string(5)}",
                "email": f"empty.test.{random_string(5)}@example.com",
                "status": "New"}
        )
        volunteer_doc.insert(ignore_permissions=True)

        # Test all methods with empty volunteer
        start_time = time.time()

        assignments = volunteer_doc.get_aggregated_assignments()
        history = volunteer_doc.get_volunteer_history()
        has_assignments = volunteer_doc.has_active_assignments_optimized()
        volunteer_doc.update_status()

        total_time = time.time() - start_time

        print(f"✅ Empty volunteer operations completed in {total_time:.4f}s")
        print(f"Assignments: {len(assignments)}, History: {len(history)}, Has assignments: {has_assignments}")
        print(f"Status: {volunteer_doc.status}")

        # Clean up
        volunteer_doc.delete(ignore_permissions=True)

        return total_time < 2.0  # Should complete within 2 seconds

    except Exception as e:
        print(f"❌ Volunteer performance edge case test failed: {str(e)}")
        return False


def main():
    """Run all volunteer tests"""
    print("🧪 Running Volunteer doctype concurrency and performance tests...")

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    results = []

    try:
        # Test volunteer query optimization
        results.append(test_volunteer_query_optimization())

        # Test volunteer concurrency
        results.append(test_volunteer_concurrency())

        # Test activity management
        results.append(test_volunteer_activity_management())

        # Test performance edge cases
        results.append(test_volunteer_performance_edge_cases())

    finally:
        frappe.destroy()

    # Summary
    passed = sum(results)
    total = len(results)

    print(f"\n📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All Volunteer doctype fixes working correctly!")
        return True
    else:
        print("⚠️  Some tests failed - please review the fixes")
        return False


if __name__ == "__main__":
    import sys

    success = main()
    sys.exit(0 if success else 1)
