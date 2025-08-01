import frappe


@frappe.whitelist()
def debug_optimization_issues():
    """Debug why the optimization is performing poorly"""

    results = {}

    # Check computed field population
    computed_stats = frappe.db.sql(
        """
        SELECT
            COUNT(*) as total_members,
            COUNT(address_fingerprint) as members_with_fingerprint,
            COUNT(normalized_address_line) as members_with_normalized_line,
            COUNT(normalized_city) as members_with_normalized_city,
            COUNT(primary_address) as members_with_address
        FROM `tabMember`
        WHERE primary_address IS NOT NULL
    """,
        as_dict=True,
    )[0]

    results["computed_field_stats"] = computed_stats

    # Check index usage
    try:
        index_info = frappe.db.sql(
            """
            SHOW INDEX FROM `tabMember`
            WHERE Key_name LIKE 'idx_member%'
        """,
            as_dict=True,
        )
        results["available_indexes"] = index_info
    except Exception as e:
        results["index_error"] = str(e)

    # Test a specific member's computed fields
    test_member = frappe.db.sql(
        """
        SELECT name, primary_address, address_fingerprint,
               normalized_address_line, normalized_city, address_last_updated
        FROM `tabMember`
        WHERE primary_address IS NOT NULL
        LIMIT 1
    """,
        as_dict=True,
    )

    if test_member:
        member_data = test_member[0]
        results["sample_member"] = member_data

        # Check if computed fields need updating
        if member_data["primary_address"]:
            try:
                address = frappe.get_doc("Address", member_data["primary_address"])
                results["sample_address"] = {
                    "name": address.name,
                    "address_line1": address.address_line1,
                    "city": address.city,
                }

                # Check what the normalizer would produce
                from verenigingen.utils.address_matching.dutch_address_normalizer import (
                    DutchAddressNormalizer,
                )

                normalized_line, normalized_city, fingerprint = DutchAddressNormalizer.normalize_address_pair(
                    address.address_line1 or "", address.city or ""
                )

                results["expected_computed_values"] = {
                    "normalized_line": normalized_line,
                    "normalized_city": normalized_city,
                    "fingerprint": fingerprint,
                }

                results["computed_fields_match"] = (
                    member_data["normalized_address_line"] == normalized_line
                    and member_data["normalized_city"] == normalized_city
                    and member_data["address_fingerprint"] == fingerprint
                )

            except Exception as e:
                results["sample_member_error"] = str(e)

    # Check query performance for different approaches
    if test_member:
        member_name = test_member[0]["name"]
        fingerprint = test_member[0]["address_fingerprint"]

        # Test fingerprint query
        if fingerprint:
            import time

            start_time = time.time()

            fingerprint_results = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabMember`
                WHERE address_fingerprint = %s
                    AND name != %s
            """,
                (fingerprint, member_name),
            )

            fingerprint_duration = (time.time() - start_time) * 1000
            results["fingerprint_query_test"] = {
                "duration_ms": round(fingerprint_duration, 2),
                "result_count": fingerprint_results[0][0] if fingerprint_results else 0,
            }

    return results


@frappe.whitelist()
def test_direct_query_performance():
    """Test direct SQL query performance vs the optimized matcher"""

    # Get a test member
    test_member = frappe.db.sql(
        """
        SELECT name, primary_address, address_fingerprint
        FROM `tabMember`
        WHERE address_fingerprint IS NOT NULL
        LIMIT 1
    """,
        as_dict=True,
    )[0]

    results = {}

    # Test 1: Direct fingerprint query (what should be fastest)
    import time

    start_time = time.time()
    direct_results = frappe.db.sql(
        """
        SELECT
            m.name,
            m.full_name,
            m.email,
            m.status,
            m.member_since,
            m.birth_date,
            'Unknown' as relationship,
            CASE
                WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) < 18 THEN 'Minor'
                WHEN TIMESTAMPDIFF(YEAR, m.birth_date, CURDATE()) >= 65 THEN 'Senior'
                ELSE 'Adult'
            END as age_group
        FROM `tabMember` m
        WHERE m.address_fingerprint = %s
            AND m.name != %s
            AND m.status IN ('Active', 'Pending', 'Suspended')
        ORDER BY m.member_since ASC, m.full_name ASC
        LIMIT 20
    """,
        (test_member["address_fingerprint"], test_member["name"]),
        as_dict=True,
    )

    direct_duration = (time.time() - start_time) * 1000

    # Test 2: Using the SimpleOptimizedAddressMatcher
    from verenigingen.utils.address_matching.simple_optimized_matcher import SimpleOptimizedAddressMatcher

    member_doc = frappe.get_doc("Member", test_member["name"])

    start_time = time.time()
    optimized_results = SimpleOptimizedAddressMatcher.get_other_members_at_address_simple(member_doc)
    optimized_duration = (time.time() - start_time) * 1000

    # Test 3: Using the Member method
    start_time = time.time()
    member_method_results = member_doc.get_other_members_at_address()
    member_method_duration = (time.time() - start_time) * 1000

    return {
        "test_member": test_member["name"],
        "fingerprint": test_member["address_fingerprint"],
        "direct_sql": {"duration_ms": round(direct_duration, 2), "result_count": len(direct_results)},
        "optimized_matcher": {
            "duration_ms": round(optimized_duration, 2),
            "result_count": len(optimized_results),
        },
        "member_method": {
            "duration_ms": round(member_method_duration, 2),
            "result_count": len(member_method_results),
        },
        "performance_analysis": {
            "direct_vs_optimized_overhead_ms": round(optimized_duration - direct_duration, 2),
            "optimized_vs_member_overhead_ms": round(member_method_duration - optimized_duration, 2),
        },
    }
