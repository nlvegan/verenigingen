import frappe


@frappe.whitelist()
def check_current_database_state():
    """Check current database indexes and performance stats"""

    results = {}

    # Check Address table indexes
    try:
        address_indexes = frappe.db.sql(
            """
            SHOW INDEX FROM `tabAddress`
            WHERE Key_name != 'PRIMARY'
        """,
            as_dict=True,
        )
        results["address_indexes"] = address_indexes
    except Exception as e:
        results["address_indexes_error"] = str(e)

    # Check Member table indexes
    try:
        member_indexes = frappe.db.sql(
            """
            SHOW INDEX FROM `tabMember`
            WHERE Key_name != 'PRIMARY'
        """,
            as_dict=True,
        )
        results["member_indexes"] = member_indexes
    except Exception as e:
        results["member_indexes_error"] = str(e)

    # Check table sizes and row counts
    try:
        table_stats = frappe.db.sql(
            """
            SELECT table_name, table_rows,
                   ROUND(((data_length + index_length) / 1024 / 1024), 2) AS size_mb
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
                AND table_name IN ('tabAddress', 'tabMember')
            ORDER BY (data_length + index_length) DESC
        """,
            as_dict=True,
        )
        results["table_stats"] = table_stats
    except Exception as e:
        results["table_stats_error"] = str(e)

    # Check current address matching performance with sample
    try:
        # Get a sample member with address
        sample_member = frappe.db.sql(
            """
            SELECT name, primary_address
            FROM `tabMember`
            WHERE primary_address IS NOT NULL
            LIMIT 1
        """,
            as_dict=True,
        )

        if sample_member:
            # Test current performance
            import time

            start_time = time.time()

            # Simulate current O(N) query
            all_addresses = frappe.db.sql(
                """
                SELECT name, address_line1, city
                FROM `tabAddress`
                WHERE address_line1 IS NOT NULL AND address_line1 != ''
            """,
                as_dict=True,
            )

            query_time = time.time() - start_time
            results["current_performance"] = {
                "address_count": len(all_addresses),
                "query_time_ms": round(query_time * 1000, 2),
                "sample_member": sample_member[0]["name"] if sample_member else None,
            }
    except Exception as e:
        results["performance_test_error"] = str(e)

    return results
