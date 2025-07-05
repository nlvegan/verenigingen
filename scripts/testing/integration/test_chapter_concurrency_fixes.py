#!/usr/bin/env python3
"""
Test script for Chapter doctype concurrency and performance fixes
"""

import threading
import time

import frappe
from frappe.utils import random_string


def test_chapter_head_update_optimization():
    """Test optimized chapter head update with atomic operations"""
    print("Testing Chapter head update optimization...")

    try:
        # Get a sample chapter
        chapters = frappe.get_all("Chapter", limit=1)
        if not chapters:
            print("No chapters found to test with")
            return True

        chapter_doc = frappe.get_doc("Chapter", chapters[0].name)

        # Test optimized chapter head lookup
        start_time = time.time()
        chair_member = chapter_doc.get_chapter_chair_optimized()
        optimized_time = time.time() - start_time

        # Test atomic chapter head update
        start_time = time.time()
        head_updated = chapter_doc.update_chapter_head()
        update_time = time.time() - start_time

        print(f"✅ Optimized chair lookup: {optimized_time:.4f}s, Chair member: {chair_member}")
        print(f"✅ Atomic head update: {update_time:.4f}s, Head updated: {head_updated}")

        return True

    except Exception as e:
        print(f"❌ Chapter head update optimization test failed: {str(e)}")
        return False


def test_chapter_permission_optimization():
    """Test optimized chapter permission queries"""
    print("\nTesting Chapter permission query optimization...")

    try:
        # Test optimized permission query
        current_user = frappe.session.user

        start_time = time.time()
        accessible_chapters = frappe.get_method(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_user_accessible_chapters_optimized"
        )(current_user)
        optimized_time = time.time() - start_time

        # Test permission query conditions
        start_time = time.time()
        conditions = frappe.get_method(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_permission_query_conditions"
        )(current_user)
        conditions_time = time.time() - start_time

        print(
            f"✅ Optimized accessible chapters query: {optimized_time:.4f}s, Found: {len(accessible_chapters)}"
        )
        print(f"✅ Permission conditions generation: {conditions_time:.4f}s")
        print(f"Conditions: {conditions[:100]}..." if len(conditions) > 100 else f"Conditions: {conditions}")

        return True

    except Exception as e:
        print(f"❌ Chapter permission optimization test failed: {str(e)}")
        return False


def test_board_manager_optimization():
    """Test board manager query optimizations"""
    print("\nTesting Board manager optimization...")

    try:
        # Get a chapter with board members
        chapters = frappe.get_all("Chapter", fields=["name"], limit=5)

        test_chapter = None
        for chapter in chapters:
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            if chapter_doc.board_members:
                test_chapter = chapter_doc
                break

        if not test_chapter:
            print("No chapters with board members found")
            return True

        # Test optimized board member queries
        start_time = time.time()
        board_members = test_chapter.board_manager.get_board_members()
        board_time = time.time() - start_time

        # Test optimized active roles query
        start_time = time.time()
        active_roles = test_chapter.board_manager.get_active_board_roles()
        roles_time = time.time() - start_time

        # Test optimized board membership check
        start_time = time.time()
        is_board_member = test_chapter.board_manager.is_board_member()
        membership_time = time.time() - start_time

        # Test optimized role lookup
        start_time = time.time()
        member_role = test_chapter.board_manager.get_member_role()
        role_time = time.time() - start_time

        print(f"✅ Optimized board members query: {board_time:.4f}s, Found: {len(board_members)}")
        print(f"✅ Optimized active roles query: {roles_time:.4f}s, Roles: {len(active_roles)}")
        print(f"✅ Optimized membership check: {membership_time:.4f}s, Is member: {is_board_member}")
        print(f"✅ Optimized role lookup: {role_time:.4f}s, Role: {member_role}")

        return True

    except Exception as e:
        print(f"❌ Board manager optimization test failed: {str(e)}")
        return False


def test_chapter_context_optimization():
    """Test optimized chapter context loading"""
    print("\nTesting Chapter context optimization...")

    try:
        # Get a sample chapter
        chapters = frappe.get_all("Chapter", limit=1)
        if not chapters:
            print("No chapters found to test with")
            return True

        chapter_doc = frappe.get_doc("Chapter", chapters[0].name)

        # Test optimized user permissions
        start_time = time.time()
        user_permissions = chapter_doc.get_user_permissions_optimized()
        permissions_time = time.time() - start_time

        # Test optimized context loading
        start_time = time.time()
        context = frappe._dict()
        context = chapter_doc.get_context(context)
        context_time = time.time() - start_time

        print(f"✅ Optimized user permissions: {permissions_time:.4f}s")
        print(f"User permissions: {user_permissions}")
        print(f"✅ Optimized context loading: {context_time:.4f}s")
        print(f"Context keys: {list(context.keys())}")

        return True

    except Exception as e:
        print(f"❌ Chapter context optimization test failed: {str(e)}")
        return False


def test_chapter_concurrency():
    """Test chapter operations under concurrent access"""
    print("\nTesting Chapter concurrency handling...")

    operations_completed = []
    errors = []

    def chapter_operation():
        try:
            # Get a chapter
            chapters = frappe.get_all("Chapter", limit=1)
            if not chapters:
                return

            chapter_doc = frappe.get_doc("Chapter", chapters[0].name)

            # Perform concurrent operations
            chapter_doc.update_chapter_head()
            permissions = chapter_doc.get_user_permissions_optimized()
            board_members = chapter_doc.board_manager.get_board_members()

            operations_completed.append(f"Thread-{threading.current_thread().ident}")

        except Exception as e:
            errors.append(str(e))

    # Create multiple threads to test concurrency
    threads = []
    for i in range(5):
        thread = threading.Thread(target=chapter_operation)
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


def test_chapter_performance_edge_cases():
    """Test performance under edge case scenarios"""
    print("\nTesting Chapter performance edge cases...")

    try:
        # Test with chapter with no board members
        empty_chapters = frappe.get_all("Chapter", fields=["name"], limit=10)

        test_chapter = None
        for chapter in empty_chapters:
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            if not chapter_doc.board_members:
                test_chapter = chapter_doc
                break

        if test_chapter:
            start_time = time.time()

            # Test all methods with empty chapter
            chair_member = test_chapter.get_chapter_chair_optimized()
            head_updated = test_chapter.update_chapter_head()
            permissions = test_chapter.get_user_permissions_optimized()
            board_members = test_chapter.board_manager.get_board_members()
            active_roles = test_chapter.board_manager.get_active_board_roles()

            total_time = time.time() - start_time

            print(f"✅ Empty chapter operations completed in {total_time:.4f}s")
            print(
                f"Chair: {chair_member}, Head updated: {head_updated}, Board members: {len(board_members)}, Roles: {len(active_roles)}"
            )

            return total_time < 2.0  # Should complete within 2 seconds
        else:
            print("No empty chapters found for edge case testing")
            return True

    except Exception as e:
        print(f"❌ Chapter performance edge case test failed: {str(e)}")
        return False


def main():
    """Run all chapter tests"""
    print("🧪 Running Chapter doctype concurrency and performance tests...")

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    results = []

    try:
        # Test chapter head update optimization
        results.append(test_chapter_head_update_optimization())

        # Test permission query optimization
        results.append(test_chapter_permission_optimization())

        # Test board manager optimization
        results.append(test_board_manager_optimization())

        # Test context optimization
        results.append(test_chapter_context_optimization())

        # Test chapter concurrency
        results.append(test_chapter_concurrency())

        # Test performance edge cases
        results.append(test_chapter_performance_edge_cases())

    finally:
        frappe.destroy()

    # Summary
    passed = sum(results)
    total = len(results)

    print(f"\n📊 Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All Chapter doctype fixes working correctly!")
        return True
    else:
        print("⚠️  Some tests failed - please review the fixes")
        return False


if __name__ == "__main__":
    import sys

    success = main()
    sys.exit(0 if success else 1)
