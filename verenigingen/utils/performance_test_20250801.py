#!/usr/bin/env python3
"""
Performance test for team validation - temporary diagnostic

Created: 2025-08-01
Purpose: Test performance of unique role validation
TODO: Remove after performance assessment complete
"""

import time

import frappe


@frappe.whitelist()
def test_team_validation_performance():
    """Test performance of team validation with various team sizes"""

    results = ["=== Team Validation Performance Test ==="]

    try:
        volunteers = frappe.get_all("Volunteer", limit=20)
        if len(volunteers) < 5:
            return "Need at least 5 volunteers for performance testing"

        # Test different team sizes
        team_sizes = [5, 10, 15, min(20, len(volunteers))]

        for size in team_sizes:
            if size > len(volunteers):
                continue

            results.append(f"\nTesting team size: {size} members")

            # Create test team
            team = frappe.get_doc(
                {
                    "doctype": "Team",
                    "team_name": f"Perf Test {size} {int(time.time())}",
                    "status": "Active",
                    "team_type": "Project Team",
                    "start_date": frappe.utils.today(),
                }
            )
            team.insert()

            # Add members
            for i in range(size):
                vol = volunteers[i]
                team.append(
                    "team_members",
                    {
                        "volunteer": vol.name,
                        "team_role": "Team Member",
                        "from_date": frappe.utils.today(),
                        "is_active": 1,
                        "status": "Active",
                    },
                )

            # Test validation performance
            start_time = time.time()
            team.validate_unique_roles()
            validation_time = (time.time() - start_time) * 1000

            # Test full save performance
            start_time = time.time()
            team.save()
            save_time = (time.time() - start_time) * 1000

            results.append(f"  Validation only: {validation_time:.2f}ms")
            results.append(f"  Full save: {save_time:.2f}ms")

            # Test with unique role conflict
            team.append(
                "team_members",
                {
                    "volunteer": volunteers[size].name if size < len(volunteers) else volunteers[0].name,
                    "team_role": "Team Leader",
                    "from_date": frappe.utils.today(),
                    "is_active": 1,
                    "status": "Active",
                },
            )
            team.append(
                "team_members",
                {
                    "volunteer": volunteers[size + 1].name
                    if size + 1 < len(volunteers)
                    else volunteers[1].name,
                    "team_role": "Team Leader",
                    "from_date": frappe.utils.today(),
                    "is_active": 1,
                    "status": "Active",
                },
            )

            # Test validation with conflict
            start_time = time.time()
            try:
                team.validate_unique_roles()
                results.append("  ❌ ERROR: Unique role conflict not detected!")
            except frappe.ValidationError as e:
                conflict_time = (time.time() - start_time) * 1000
                results.append(f"  Conflict detection: {conflict_time:.2f}ms")
                results.append(f"  ✅ Unique role conflict properly detected")

            # Clean up
            frappe.delete_doc("Team", team.name)

        results.append("\n=== Performance Test Summary ===")
        results.append("✅ All performance tests completed successfully")

    except Exception as e:
        results.append(f"❌ ERROR: {e}")
        import traceback

        results.append(f"Traceback: {traceback.format_exc()}")

    return "\n".join(results)
