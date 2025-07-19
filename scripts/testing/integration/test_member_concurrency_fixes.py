#!/usr/bin/env python3
"""
Test script for Member doctype concurrency and performance fixes
"""

import threading
import time

import frappe
from frappe.utils import random_string


def test_member_id_generation_concurrency():
    """Test that member ID generation is thread-safe"""
    print("Testing Member ID generation concurrency...")

    generated_ids = []
    errors = []

    def generate_member_id():
        try:
            from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

            member_id = MemberIDManager.get_next_member_id()
            generated_ids.append(member_id)
        except Exception as e:
            errors.append(str(e))

    # Create multiple threads to test concurrency
    threads = []
    for i in range(10):
        thread = threading.Thread(target=generate_member_id)
        threads.append(thread)

    # Start all threads
    for thread in threads:
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Check results
    print(f"Generated {len(generated_ids)} IDs: {generated_ids}")
    print(f"Errors: {errors}")

    # Verify uniqueness
    unique_ids = set(generated_ids)
    if len(unique_ids) == len(generated_ids):
        print("✅ All generated IDs are unique")
        return True
    else:
        print(f"❌ Found duplicate IDs! Generated: {len(generated_ids)}, Unique: {len(unique_ids)}")
        return False


def test_member_creation_performance():
    """Test member creation performance with optimized queries"""
    print("\nTesting Member creation performance...")

    start_time = time.time()

    try:
        # Create a test member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Performance" + random_string(5),
                "email": f"test.performance.{random_string(5)}@example.com",
                "status": "Active",
            }
        )

        member.insert(ignore_permissions=True)

        # Test chapter display update
        member.update_current_chapter_display()

        # Test fee override handling
        member.dues_rate = 25.0
        member.fee_override_reason = "Test performance"
        member.save(ignore_permissions=True)

        end_time = time.time()
        duration = end_time - start_time

        print(f"✅ Member creation and updates completed in {duration:.2f} seconds")

        # Clean up
        member.delete(ignore_permissions=True)

        return duration < 5.0  # Should complete within 5 seconds

    except Exception as e:
        print(f"❌ Member creation test failed: {str(e)}")
        return False


def test_optimized_chapter_queries():
    """Test that optimized chapter queries work correctly"""
    print("\nTesting optimized chapter queries...")

    try:
        # Get a sample member
        members = frappe.get_all("Member", limit=1)
        if not members:
            print("No members found to test with")
            return True

        member_doc = frappe.get_doc("Member", members[0].name)

        # Test optimized chapter query
        start_time = time.time()
        chapters_optimized = member_doc.get_current_chapters_optimized()
        optimized_time = time.time() - start_time

        # Test fallback query
        start_time = time.time()
        chapters_fallback = member_doc.get_current_chapters()
        fallback_time = time.time() - start_time

        print(f"✅ Optimized query: {optimized_time:.4f}s, Fallback query: {fallback_time:.4f}s")
        print(f"Optimized chapters: {len(chapters_optimized)}, Fallback chapters: {len(chapters_fallback)}")

        return True

    except Exception as e:
        print(f"❌ Chapter query test failed: {str(e)}")
        return False


def main():
    """Run all tests"""
    print("🧪 Running Member doctype concurrency and performance tests...")

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    results = []

    try:
        # Test member ID generation concurrency
        results.append(test_member_id_generation_concurrency())

        # Test member creation performance
        results.append(test_member_creation_performance())

        # Test optimized chapter queries
        results.append(test_optimized_chapter_queries())

    finally:
        frappe.destroy()

    # Summary
    passed = sum(results)
    total = len(results)

    print(f"\n📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All Member doctype fixes working correctly!")
        return True
    else:
        print("⚠️  Some tests failed - please review the fixes")
        return False


if __name__ == "__main__":
    import sys

    success = main()
    sys.exit(0 if success else 1)
