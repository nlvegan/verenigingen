#!/usr/bin/env python3
"""
Performance Benchmark for N+1 Query Optimization
================================================

Comprehensive benchmarking suite to validate the member listing API optimization
claims with realistic datasets and actual performance measurements.
"""

import statistics
import time

import frappe
from frappe.utils import random_string

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory


class PerformanceBenchmark:
    """Benchmark suite for member listing API performance"""

    def __init__(self):
        self.factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
        self.results = {}

    def setup_test_data(self, member_count=500, chapter_count=10):
        """Create realistic test dataset"""
        print(f"Creating {member_count} members across {chapter_count} chapters...")

        # Get or create region for chapters
        regions = frappe.get_all("Region", limit=1, pluck="name")
        if regions:
            region_name = regions[0]
        else:
            region = frappe.get_doc(
                {"doctype": "Region", "region_name": f"Benchmark-Region-{random_string(5)}"}
            )
            region.insert()
            region_name = region.name

        # Create chapters
        chapters = []
        for i in range(chapter_count):
            chapter = self.factory.ensure_test_chapter(
                chapter_name=f"Benchmark-Chapter-{i + 1}-{random_string(5)}",
                attributes={"region": region_name},
            )
            chapters.append(chapter)

        print(f"Created {len(chapters)} chapters")

        # Create members and assign to chapters
        members = []
        for i in range(member_count):
            member = self.factory.create_member(
                first_name=f"BenchMember{i + 1}",
                last_name=f"Test-{random_string(3)}",
                birth_date="1990-01-01",
            )
            members.append(member)

            # Assign to 1-3 chapters randomly (realistic distribution)
            import random

            num_chapters = random.choices([0, 1, 2, 3], weights=[10, 60, 25, 5])[0]

            if num_chapters > 0:
                selected_chapters = random.sample(chapters, min(num_chapters, len(chapters)))
                for chapter in selected_chapters:
                    # Add to chapter's member table
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

            if (i + 1) % 100 == 0:
                print(f"Created {i + 1} members...")

        print(f"✅ Test data setup complete: {len(members)} members, {len(chapters)} chapters")
        return members, chapters

    def benchmark_optimized_api(self, limit=100, iterations=5):
        """Benchmark the optimized API with query counting and timing"""
        print(f"\n🚀 Benchmarking OPTIMIZED API (limit={limit}, iterations={iterations})")

        from verenigingen.api.member_management import get_members_with_chapter_info

        times = []
        query_counts = []

        for i in range(iterations):
            # Count queries
            query_count = 0
            original_sql = frappe.db.sql

            def counting_sql(*args, **kwargs):
                nonlocal query_count
                query_count += 1
                return original_sql(*args, **kwargs)

            frappe.db.sql = counting_sql

            try:
                start_time = time.time()
                result = get_members_with_chapter_info(limit=limit)
                end_time = time.time()

                execution_time = (end_time - start_time) * 1000  # Convert to ms
                times.append(execution_time)
                query_counts.append(query_count)

                print(
                    f"  Run {i + 1}: {execution_time:.2f}ms, {query_count} queries, {result['total_count']} members"
                )

            finally:
                frappe.db.sql = original_sql

        avg_time = statistics.mean(times)
        avg_queries = statistics.mean(query_counts)

        self.results["optimized"] = {
            "avg_time_ms": avg_time,
            "avg_queries": avg_queries,
            "times": times,
            "query_counts": query_counts,
        }

        print(f"📊 OPTIMIZED Results: {avg_time:.2f}ms avg, {avg_queries:.1f} queries avg")
        return avg_time, avg_queries

    def benchmark_n_plus_1_simulation(self, limit=100, iterations=5):
        """Simulate N+1 pattern for comparison"""
        print(f"\n🐌 Benchmarking N+1 SIMULATION (limit={limit}, iterations={iterations})")

        times = []
        query_counts = []

        for i in range(iterations):
            query_count = 0
            original_sql = frappe.db.sql

            def counting_sql(*args, **kwargs):
                nonlocal query_count
                query_count += 1
                return original_sql(*args, **kwargs)

            frappe.db.sql = counting_sql

            try:
                start_time = time.time()

                # STEP 1: Get members (1 query)
                members = frappe.get_all(
                    "Member",
                    filters={"docstatus": ["<", 2]},
                    fields=["name", "full_name", "email", "status"],
                    limit=limit,
                    order_by="full_name asc",
                )

                # STEP 2: N+1 pattern - get chapters for each member individually
                for member in members:
                    # Get chapter relationships for this member (N queries)
                    chapter_relationships = frappe.get_all(
                        "Chapter Member",
                        filters={"member": member["name"], "enabled": 1},
                        fields=["parent", "status", "chapter_join_date"],
                    )

                    # Get chapter info for each relationship (potentially more queries)
                    member_chapters = []
                    for rel in chapter_relationships:
                        if rel.get("parent"):
                            chapter = frappe.get_doc("Chapter", rel["parent"])
                            member_chapters.append(
                                {
                                    "chapter_name": chapter.name,
                                    "region": chapter.region,
                                    "status": rel.get("status", "Active"),
                                }
                            )

                    member["chapters"] = member_chapters

                end_time = time.time()
                execution_time = (end_time - start_time) * 1000
                times.append(execution_time)
                query_counts.append(query_count)

                print(f"  Run {i + 1}: {execution_time:.2f}ms, {query_count} queries, {len(members)} members")

            finally:
                frappe.db.sql = original_sql

        avg_time = statistics.mean(times)
        avg_queries = statistics.mean(query_counts)

        self.results["n_plus_1"] = {
            "avg_time_ms": avg_time,
            "avg_queries": avg_queries,
            "times": times,
            "query_counts": query_counts,
        }

        print(f"📊 N+1 Results: {avg_time:.2f}ms avg, {avg_queries:.1f} queries avg")
        return avg_time, avg_queries

    def generate_performance_report(self):
        """Generate comprehensive performance analysis report"""
        if "optimized" not in self.results or "n_plus_1" not in self.results:
            print("❌ Missing benchmark results - run both benchmarks first")
            return

        optimized = self.results["optimized"]
        n_plus_1 = self.results["n_plus_1"]

        time_improvement = (
            (n_plus_1["avg_time_ms"] - optimized["avg_time_ms"]) / n_plus_1["avg_time_ms"]
        ) * 100
        query_reduction = (
            (n_plus_1["avg_queries"] - optimized["avg_queries"]) / n_plus_1["avg_queries"]
        ) * 100

        print("\n" + "=" * 60)
        print("🏁 PERFORMANCE BENCHMARK RESULTS")
        print("=" * 60)
        print(
            f"Optimized API:  {optimized['avg_time_ms']:.2f}ms avg ({optimized['avg_queries']:.1f} queries)"
        )
        print(f"N+1 Pattern:    {n_plus_1['avg_time_ms']:.2f}ms avg ({n_plus_1['avg_queries']:.1f} queries)")
        print("")
        print(f"⚡ Speed Improvement: {time_improvement:.1f}% faster")
        print(f"📉 Query Reduction:   {query_reduction:.1f}% fewer queries")
        print("")

        if query_reduction > 80:
            print("🚀 EXCELLENT: >80% query reduction achieved!")
        elif query_reduction > 50:
            print("✅ GOOD: >50% query reduction achieved")
        elif query_reduction > 20:
            print("⚠️  MODERATE: Some improvement but room for optimization")
        else:
            print("❌ POOR: Minimal improvement - optimization may not be working")

        print("")
        print("Query Count Analysis:")
        print("  Expected optimized queries: ~3")
        print(f"  Actual optimized queries:   {optimized['avg_queries']:.1f}")
        print(f"  N+1 pattern queries:        {n_plus_1['avg_queries']:.1f}")

        if optimized["avg_queries"] <= 5:
            print("✅ Query count meets optimization goals")
        else:
            print("❌ Query count higher than expected - investigation needed")

        return {
            "time_improvement_percent": time_improvement,
            "query_reduction_percent": query_reduction,
            "optimized_avg_queries": optimized["avg_queries"],
            "n_plus_1_avg_queries": n_plus_1["avg_queries"],
        }

    def run_full_benchmark(self, member_count=500, chapter_count=10, test_limit=100):
        """Run complete benchmark suite"""
        print("🎯 STARTING PERFORMANCE BENCHMARK")
        print(f"Dataset: {member_count} members, {chapter_count} chapters")
        print(f"Test limit: {test_limit} members per API call")

        try:
            # Setup test data
            members, chapters = self.setup_test_data(member_count, chapter_count)

            # Run benchmarks
            self.benchmark_optimized_api(limit=test_limit)
            self.benchmark_n_plus_1_simulation(limit=test_limit)

            # Generate report
            results = self.generate_performance_report()

            return results

        except Exception as e:
            print(f"❌ Benchmark failed: {e}")
            import traceback

            traceback.print_exc()
            return None


def run_benchmark():
    """Main benchmark execution function"""
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        benchmark = PerformanceBenchmark()

        # Test different scales
        scenarios = [
            {"member_count": 100, "chapter_count": 5, "test_limit": 50, "name": "Small"},
            {"member_count": 500, "chapter_count": 10, "test_limit": 100, "name": "Medium"},
            {"member_count": 1000, "chapter_count": 20, "test_limit": 200, "name": "Large"},
        ]

        all_results = {}

        for scenario in scenarios:
            print(f"\n{'=' * 80}")
            print(f"🎯 SCENARIO: {scenario['name']} Scale Test")
            print(f"{'=' * 80}")

            result = benchmark.run_full_benchmark(
                member_count=scenario["member_count"],
                chapter_count=scenario["chapter_count"],
                test_limit=scenario["test_limit"],
            )

            if result:
                all_results[scenario["name"]] = result

        # Summary across all scenarios
        print(f"\n{'=' * 80}")
        print("🏆 BENCHMARK SUMMARY ACROSS ALL SCENARIOS")
        print(f"{'=' * 80}")

        for scenario_name, result in all_results.items():
            print(
                f"{scenario_name:8}: {result['time_improvement_percent']:5.1f}% faster, {result['query_reduction_percent']:5.1f}% fewer queries"
            )

        return all_results

    finally:
        frappe.destroy()


if __name__ == "__main__":
    results = run_benchmark()
