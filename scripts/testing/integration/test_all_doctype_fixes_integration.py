#!/usr/bin/env python3
"""
Integration test script for all doctype concurrency and performance fixes
Tests Member, Volunteer, and Chapter doctypes together
"""

import threading
import time

import frappe
from frappe.utils import random_string


def test_member_volunteer_integration():
    """Test Member and Volunteer doctype integration with optimizations"""
    print("Testing Member-Volunteer integration...")

    try:
        # Get a member with volunteer record
        members_with_volunteers = frappe.db.sql(
            """
            SELECT m.name as member_name, v.name as volunteer_name
            FROM `tabMember` m
            JOIN `tabVolunteer` v ON v.member = m.name
            LIMIT 1
        """,
            as_dict=True,
        )

        if not members_with_volunteers:
            print("No member-volunteer pairs found")
            return True

        member_name = members_with_volunteers[0].member_name
        volunteer_name = members_with_volunteers[0].volunteer_name

        # Test optimized member operations
        start_time = time.time()
        member_doc = frappe.get_doc("Member", member_name)
        member_doc.update_current_chapter_display()
        member_time = time.time() - start_time

        # Test optimized volunteer operations
        start_time = time.time()
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        assignments = volunteer_doc.get_aggregated_assignments()
        history = volunteer_doc.get_volunteer_history()
        volunteer_time = time.time() - start_time

        print(f"✅ Member operations: {member_time:.4f}s")
        print(
            f"✅ Volunteer operations: {volunteer_time:.4f}s, Assignments: {len(assignments)}, History: {len(history)}"
        )

        return True

    except Exception as e:
        print(f"❌ Member-Volunteer integration test failed: {str(e)}")
        return False


def test_chapter_member_volunteer_integration():
    """Test Chapter, Member, and Volunteer integration"""
    print("\nTesting Chapter-Member-Volunteer integration...")

    try:
        # Get a chapter with board members
        chapters_with_board = frappe.db.sql(
            """
            SELECT c.name as chapter_name, cbm.volunteer, v.member
            FROM `tabChapter` c
            JOIN `tabChapter Board Member` cbm ON cbm.parent = c.name
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE cbm.is_active = 1 AND v.member IS NOT NULL
            LIMIT 1
        """,
            as_dict=True,
        )

        if not chapters_with_board:
            print("No chapters with active board members found")
            return True

        chapter_name = chapters_with_board[0].chapter_name
        volunteer_name = chapters_with_board[0].volunteer
        member_name = chapters_with_board[0].member

        # Test optimized chapter operations
        start_time = time.time()
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chair_member = chapter_doc.get_chapter_chair_optimized()
        head_updated = chapter_doc.update_chapter_head()
        permissions = chapter_doc.get_user_permissions_optimized()
        chapter_time = time.time() - start_time

        # Test board manager optimizations
        start_time = time.time()
        board_members = chapter_doc.board_manager.get_board_members()
        is_board_member = chapter_doc.board_manager.is_board_member(member_name=member_name)
        member_role = chapter_doc.board_manager.get_member_role(member_name=member_name)
        board_time = time.time() - start_time

        # Test volunteer assignments in context of chapter
        start_time = time.time()
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        assignments = volunteer_doc.get_aggregated_assignments()
        # Find chapter board assignments
        chapter_assignments = [a for a in assignments if a.get("source_type") == "Board Position"]
        volunteer_integration_time = time.time() - start_time

        print(
            f"✅ Chapter operations: {chapter_time:.4f}s, Chair: {chair_member}, Head updated: {head_updated}"
        )
        print(
            f"✅ Board operations: {board_time:.4f}s, Members: {len(board_members)}, Is member: {is_board_member}, Role: {member_role}"
        )
        print(
            f"✅ Volunteer integration: {volunteer_integration_time:.4f}s, Chapter assignments: {len(chapter_assignments)}"
        )

        return True

    except Exception as e:
        print(f"❌ Chapter-Member-Volunteer integration test failed: {str(e)}")
        return False


def test_permission_system_integration():
    """Test integrated permission system across all doctypes"""
    print("\nTesting Permission system integration...")

    try:
        current_user = frappe.session.user

        # Test chapter permissions
        start_time = time.time()
        accessible_chapters = frappe.get_method(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_user_accessible_chapters_optimized"
        )(current_user)
        chapter_conditions = frappe.get_method(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_chapter_permission_query_conditions"
        )(current_user)
        permission_time = time.time() - start_time

        # Test member access through chapter context
        if accessible_chapters:
            start_time = time.time()
            test_chapter = frappe.get_doc("Chapter", accessible_chapters[0])
            context = frappe._dict()
            context = test_chapter.get_context(context)
            context_time = time.time() - start_time

            print(
                f"✅ Permission queries: {permission_time:.4f}s, Accessible chapters: {len(accessible_chapters)}"
            )
            print(
                f"✅ Context loading: {context_time:.4f}s, Can view members: {context.get('is_board_member', False)}"
            )
        else:
            print("✅ Permission system working - no accessible chapters for current user")

        return True

    except Exception as e:
        print(f"❌ Permission system integration test failed: {str(e)}")
        return False


def test_concurrent_operations_integration():
    """Test concurrent operations across all doctypes"""
    print("\nTesting Concurrent operations integration...")

    operations_completed = []
    errors = []

    def integrated_operation():
        try:
            # Test member operations
            members = frappe.get_all("Member", limit=1)
            if members:
                member_doc = frappe.get_doc("Member", members[0].name)
                member_doc.update_current_chapter_display()

            # Test volunteer operations
            volunteers = frappe.get_all("Volunteer", limit=1)
            if volunteers:
                volunteer_doc = frappe.get_doc("Volunteer", volunteers[0].name)
                assignments = volunteer_doc.get_aggregated_assignments()

            # Test chapter operations
            chapters = frappe.get_all("Chapter", limit=1)
            if chapters:
                chapter_doc = frappe.get_doc("Chapter", chapters[0].name)
                chapter_doc.update_chapter_head()
                permissions = chapter_doc.get_user_permissions_optimized()

            operations_completed.append(f"Thread-{threading.current_thread().ident}")

        except Exception as e:
            errors.append(str(e))

    # Create multiple threads to test concurrency
    threads = []
    for i in range(3):  # Fewer threads for integration test
        thread = threading.Thread(target=integrated_operation)
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
        print(f"❌ Concurrent integration errors: {errors}")
        return False
    else:
        print("✅ All concurrent integration operations completed successfully")
        return True


def test_performance_benchmarks():
    """Test overall performance benchmarks"""
    print("\nTesting Performance benchmarks...")

    try:
        benchmarks = {}

        # Benchmark member ID generation (should be atomic and fast)
        start_time = time.time()
        try:
            from verenigingen.verenigingen.doctype.member.member_id_manager import MemberIDManager

            member_id = MemberIDManager.get_next_member_id()
            benchmarks["member_id_generation"] = time.time() - start_time
        except Exception as e:
            benchmarks["member_id_generation"] = f"Error: {str(e)}"

        # Benchmark volunteer aggregated assignments
        volunteers = frappe.get_all("Volunteer", limit=1)
        if volunteers:
            start_time = time.time()
            volunteer_doc = frappe.get_doc("Volunteer", volunteers[0].name)
            assignments = volunteer_doc.get_aggregated_assignments_optimized()
            benchmarks["volunteer_assignments"] = time.time() - start_time

        # Benchmark chapter permission queries
        start_time = time.time()
        accessible_chapters = frappe.get_method(
            "verenigingen.verenigingen.doctype.chapter.chapter.get_user_accessible_chapters_optimized"
        )(frappe.session.user)
        benchmarks["chapter_permissions"] = time.time() - start_time

        # Benchmark chapter head update
        chapters = frappe.get_all("Chapter", limit=1)
        if chapters:
            start_time = time.time()
            chapter_doc = frappe.get_doc("Chapter", chapters[0].name)
            chair_member = chapter_doc.get_chapter_chair_optimized()
            benchmarks["chapter_head_update"] = time.time() - start_time

        print("✅ Performance Benchmarks:")
        for operation, time_taken in benchmarks.items():
            if isinstance(time_taken, float):
                print(f"  {operation}: {time_taken:.4f}s")
            else:
                print(f"  {operation}: {time_taken}")

        # Check if all operations are within acceptable time limits
        acceptable_times = {
            "member_id_generation": 0.1,  # 100ms
            "volunteer_assignments": 0.5,  # 500ms
            "chapter_permissions": 0.3,  # 300ms
            "chapter_head_update": 0.2,  # 200ms
        }

        performance_ok = True
        for operation, time_taken in benchmarks.items():
            if isinstance(time_taken, float) and operation in acceptable_times:
                if time_taken > acceptable_times[operation]:
                    print(f"⚠️  {operation} took {time_taken:.4f}s (limit: {acceptable_times[operation]}s)")
                    performance_ok = False

        return performance_ok

    except Exception as e:
        print(f"❌ Performance benchmark test failed: {str(e)}")
        return False


def main():
    """Run all integration tests"""
    print("🧪 Running comprehensive integration tests for all doctype fixes...")

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    results = []

    try:
        # Test Member-Volunteer integration
        results.append(test_member_volunteer_integration())

        # Test Chapter-Member-Volunteer integration
        results.append(test_chapter_member_volunteer_integration())

        # Test permission system integration
        results.append(test_permission_system_integration())

        # Test concurrent operations integration
        results.append(test_concurrent_operations_integration())

        # Test performance benchmarks
        results.append(test_performance_benchmarks())

    finally:
        frappe.destroy()

    # Summary
    passed = sum(results)
    total = len(results)

    print(f"\n📊 Integration Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All integration tests passed! All doctype fixes working correctly together!")
        return True
    else:
        print("⚠️  Some integration tests failed - please review the fixes")
        return False


if __name__ == "__main__":
    import sys

    success = main()
    sys.exit(0 if success else 1)
