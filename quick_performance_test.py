import time

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory


def quick_performance_test():
    """Quick performance validation of the optimized API"""
    print("🎯 Quick Performance Test - N+1 Optimization Validation")

    factory = EnhancedTestDataFactory(seed=12345)

    # Get existing region or create one
    regions = frappe.get_all("Region", limit=1, pluck="name")
    region_name = regions[0] if regions else "test-region-performance"

    if not regions:
        region = frappe.get_doc({"doctype": "Region", "region_name": region_name})
        region.insert()

    # Create 3 chapters quickly
    chapters = []
    for i in range(3):
        chapter_name = f"PerfTest-Chapter-{i+1}"
        if not frappe.db.exists("Chapter", chapter_name):
            chapter = frappe.get_doc(
                {"doctype": "Chapter", "name": chapter_name, "region": region_name, "status": "Active"}
            )
            chapter.insert()
        else:
            chapter = frappe.get_doc("Chapter", chapter_name)
        chapters.append(chapter)

    # Create 20 members with chapter relationships
    member_names = []
    for i in range(20):
        member = factory.create_member(
            first_name=f"PerfTest{i+1}", last_name="Member", birth_date="1990-01-01"
        )
        member_names.append(member.name)

        # Assign to a chapter
        chapter = chapters[i % len(chapters)]
        chapter.append(
            "members",
            {
                "member": member.name,
                "status": "Active",
                "enabled": 1,
                "chapter_join_date": frappe.utils.today(),
            },
        )
        chapter.save()

    print(f"✅ Created {len(member_names)} members across {len(chapters)} chapters")

    # Test optimized API with query counting
    from verenigingen.api.member_management import get_members_with_chapter_info

    query_count = 0
    original_sql = frappe.db.sql

    def counting_sql(*args, **kwargs):
        nonlocal query_count
        query_count += 1
        return original_sql(*args, **kwargs)

    frappe.db.sql = counting_sql

    try:
        print("\n🚀 Testing optimized API...")
        start_time = time.time()
        result = get_members_with_chapter_info(limit=20)
        end_time = time.time()

        execution_time = (end_time - start_time) * 1000  # ms

        print(f"✅ API executed successfully")
        print(f"⏱️  Execution time: {execution_time:.2f}ms")
        print(f"🔢 Query count: {query_count}")
        print(f"👥 Members returned: {result['total_count']}")
        print(f"📊 Claimed queries: {result['query_optimization']['queries_used']}")

        # Count members with chapters
        members_with_chapters = sum(1 for m in result["members"] if m["chapters"])
        print(f"🏠 Members with chapters: {members_with_chapters}")

        # Validate query optimization
        if query_count <= 5:
            print("✅ EXCELLENT: Query count is optimal!")
        elif query_count <= 10:
            print("✅ GOOD: Query count is reasonable")
        else:
            print("⚠️  HIGH: Query count may need optimization")

        # Show actual vs claimed
        print(f"\nQuery Analysis:")
        print(f"  Claimed: {result['query_optimization']['queries_used']} queries")
        print(f"  Actual:  {query_count} queries")

        if abs(query_count - result["query_optimization"]["queries_used"]) <= 2:
            print("✅ Query count claims are accurate!")
        else:
            print("❌ Query count discrepancy detected")

        return {
            "execution_time_ms": execution_time,
            "actual_query_count": query_count,
            "claimed_query_count": result["query_optimization"]["queries_used"],
            "members_returned": result["total_count"],
            "members_with_chapters": members_with_chapters,
        }

    finally:
        frappe.db.sql = original_sql


# Run the test
frappe.init(site="dev.veganisme.net")
frappe.connect()
frappe.set_user("Administrator")

try:
    results = quick_performance_test()
    print(f"\n🎯 Performance test completed successfully!")
except Exception as e:
    print(f"❌ Test failed: {e}")
    import traceback

    traceback.print_exc()
finally:
    frappe.destroy()
