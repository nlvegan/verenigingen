#!/usr/bin/env python
"""Manual test runner for code review tests."""

import time
import frappe


def run_tests():
    """Run the manual tests."""
    print("=" * 60)
    print("Running Code Review Tests")
    print("=" * 60)

    # Test 1: MySQL Lock acquire/release
    print("\nTest 1: MySQL Lock acquire/release...")
    lock_name = f"test_lock_{int(time.time() * 1000)}"
    lock_result = frappe.db.sql("SELECT GET_LOCK(%s, 5) as acquired", (lock_name,), as_dict=True)
    assert lock_result[0].acquired == 1, "GET_LOCK should return 1"
    release_result = frappe.db.sql("SELECT RELEASE_LOCK(%s) as released", (lock_name,), as_dict=True)
    assert release_result[0].released == 1, "RELEASE_LOCK should return 1"
    print("  PASSED: Lock acquired and released successfully")

    # Test 2: Service lock helpers
    print("\nTest 2: Service lock helpers...")
    from verenigingen.services.csv_import.member_import_service import MemberImportService

    service = MemberImportService()
    lock_name2 = f"service_lock_{int(time.time() * 1000)}"
    acquired = service._acquire_advisory_lock(lock_name2, row_num=1)
    assert acquired, "Lock should be acquired"
    service._release_advisory_lock(lock_name2, row_num=1)
    print("  PASSED: Service lock helpers work correctly")

    # Test 3: Bulk context manager
    print("\nTest 3: Bulk context manager...")
    # Set flags to False (frappe.flags doesn't support delattr directly)
    frappe.flags.bulk_member_operations = False
    frappe.flags.in_bulk_import = False

    with service._bulk_context():
        assert frappe.flags.bulk_member_operations == True, "Flag should be True inside"
        assert frappe.flags.in_bulk_import == True, "Flag should be True inside"

    outside_bulk = getattr(frappe.flags, "bulk_member_operations", None)
    outside_import = getattr(frappe.flags, "in_bulk_import", None)
    # After context, flags should be restored to False (their original value)
    assert outside_bulk == False, f"Flag should be restored to False, got {outside_bulk}"
    assert outside_import == False, f"Flag should be restored to False, got {outside_import}"
    print("  PASSED: Bulk context flags properly set and restored")

    # Test 4: Email normalization
    print("\nTest 4: Email normalization...")
    from verenigingen.services.member.member_lookup_service import (
        MemberLookupService,
        LookupStrategy,
    )

    unique_id = f"TEST-{int(time.time() * 1000)}"
    test_email = f"test-email-{unique_id}@example.com"

    # Use db.insert directly to bypass all hooks
    frappe.db.sql(
        """
        INSERT INTO `tabMember` (name, first_name, last_name, email, status, creation, modified, owner, modified_by)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), 'Administrator', 'Administrator')
    """,
        (f"TEST-MEM-{unique_id}", "Test", "Email", test_email, "Pending"),
    )
    frappe.db.commit()
    member = frappe.get_doc("Member", f"TEST-MEM-{unique_id}")
    frappe.db.commit()

    try:
        lookup = MemberLookupService()

        # Test uppercase
        result = lookup.find_member({"email": test_email.upper()}, strategies=[LookupStrategy.EMAIL])
        assert result is not None, "Should find member with uppercase email"
        assert result.name == member.name

        # Test with whitespace
        result2 = lookup.find_member({"email": f"  {test_email}  "}, strategies=[LookupStrategy.EMAIL])
        assert result2 is not None, "Should find member with whitespace"
        assert result2.name == member.name

        print("  PASSED: Email normalization works for case and whitespace")
    finally:
        frappe.delete_doc("Member", member.name, force=True)
        frappe.db.commit()

    # Test 5: find_member_with_strategy
    print("\nTest 5: find_member_with_strategy...")
    unique_id2 = f"STRAT-{int(time.time() * 1000)}"
    test_email2 = f"strategy-{unique_id2}@example.com"

    # Use db.insert directly to bypass all hooks
    frappe.db.sql(
        """
        INSERT INTO `tabMember` (name, first_name, last_name, email, member_id, status, creation, modified, owner, modified_by)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW(), 'Administrator', 'Administrator')
    """,
        (f"TEST-MEM2-{unique_id2}", "Strategy", "Test", test_email2, unique_id2, "Pending"),
    )
    frappe.db.commit()
    member2 = frappe.get_doc("Member", f"TEST-MEM2-{unique_id2}")
    frappe.db.commit()

    try:
        found, strategy = lookup.find_member_with_strategy(
            {"member_id": unique_id2}, strategies=[LookupStrategy.MEMBER_ID]
        )
        assert found is not None, "Should find member"
        assert found.name == member2.name
        assert strategy == LookupStrategy.MEMBER_ID, "Strategy should be MEMBER_ID"

        # Test fallback
        found2, strategy2 = lookup.find_member_with_strategy(
            {"member_id": "NONEXISTENT", "email": test_email2},
            strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
        )
        assert found2 is not None, "Should find via email fallback"
        assert strategy2 == LookupStrategy.EMAIL, "Should have used EMAIL strategy"

        print("  PASSED: find_member_with_strategy returns correct tuple")
    finally:
        frappe.delete_doc("Member", member2.name, force=True)
        frappe.db.commit()

    # Test 6: Configuration constants
    print("\nTest 6: Configuration constants...")
    from verenigingen.services.csv_import import member_import_service

    assert 1 <= member_import_service.LOCK_TIMEOUT_SECONDS <= 60
    assert 1 <= member_import_service.LOCK_MAX_RETRIES <= 10
    assert 0.1 <= member_import_service.LOCK_RETRY_BASE_DELAY <= 5
    print("  PASSED: Configuration constants are sensible")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
