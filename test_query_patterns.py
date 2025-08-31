#!/usr/bin/env python3
import frappe
from frappe.test_runner import make_test_records


def test_api_query_patterns():
    """Test actual query patterns of the member API"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    # Enable query logging
    import logging

    logger = logging.getLogger("frappe.database")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    formatter = logging.Formatter("SQL: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Count queries manually by patching
    query_count = 0
    original_sql = frappe.db.sql

    def counting_sql(*args, **kwargs):
        nonlocal query_count
        query_count += 1
        print(f"QUERY {query_count}: {args[0][:100]}...")
        return original_sql(*args, **kwargs)

    frappe.db.sql = counting_sql

    try:
        print("Testing get_members_with_chapter_info query pattern...")
        from verenigingen.api.member_management import get_members_with_chapter_info

        print(f"\n=== Starting API call with query counting ===")
        result = get_members_with_chapter_info(limit=10)
        print(f"=== Finished API call - Total queries: {query_count} ===")

        print(f"\nResult: {result['success']}")
        print(f"Members returned: {result['total_count']}")
        print(f"Claimed queries used: {result['query_optimization']['queries_used']}")
        print(f"Actual queries counted: {query_count}")

        if query_count <= 5:
            print("✅ Query count is excellent!")
        elif query_count <= 10:
            print("✅ Query count is good")
        else:
            print("❌ Query count needs optimization")

    finally:
        frappe.db.sql = original_sql
        frappe.destroy()


if __name__ == "__main__":
    test_api_query_patterns()
