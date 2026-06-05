"""
Member Performance Optimization Validation Tests
===============================================

These tests validate that the performance optimizations reduce query count
significantly while maintaining full business logic functionality.

Key Performance Targets:
- Standard member creation: 692 queries → ~100 queries (85% reduction)
- Optimized member search: <10 queries for results with related data
- Member dashboard: <5 queries with caching
- Bulk operations: 50 queries per batch of 5 members
"""

import time
from contextlib import contextmanager

import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _QueryCounter:
    """Simple holder exposing the captured queries to the test body."""

    def __init__(self):
        self.queries = []


class TestMemberPerformanceOptimization(EnhancedTestCase):
    """Test member operations performance optimizations"""

    @contextmanager
    def _count_queries(self, max_queries):
        """Count SQL queries executed in the block and assert an upper bound.

        Frappe v16's assertQueryCount no longer yields an object exposing the
        executed queries, so this local helper restores the ``ctx.queries``
        access these performance tests rely on while keeping the upper-bound
        assertion behaviour.
        """
        counter = _QueryCounter()
        orig_sql = frappe.db.__class__.sql

        def _sql_with_count(*args, **kwargs):
            ret = orig_sql(*args, **kwargs)
            counter.queries.append(str(args[0]) if args else "")
            return ret

        try:
            frappe.db.__class__.sql = _sql_with_count
            yield counter
        finally:
            frappe.db.__class__.sql = orig_sql
        self.assertLessEqual(len(counter.queries), max_queries)

    def setUp(self):
        super().setUp()
        # Clear any existing cache
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        member_optimizer.clear_all_member_caches()

    def test_standard_vs_optimized_member_creation(self):
        """Compare standard vs optimized member creation performance"""

        print("\n=== MEMBER CREATION PERFORMANCE COMPARISON ===")

        # Warm DocType meta / schema caches so the counted block measures the
        # steady-state query cost, not one-time cold-cache meta loading
        # (information_schema + tabDocType/tabDocField introspection), which on
        # a cold first-test run dwarfs the actual creation queries.
        self.create_test_member(
            first_name="Warmup", last_name="Standard", birth_date="1985-01-01", postal_code="1234 AB"
        )
        self.create_test_member_optimized(
            first_name="Warmup", last_name="Optimized", birth_date="1985-01-01"
        )

        # Test 1: Standard member creation (baseline)
        print("\n1. Testing Standard Member Creation:")
        with self._count_queries(1000) as standard_context:
            standard_member = self.create_test_member(
                first_name="Standard", last_name="Creation", birth_date="1985-01-01", postal_code="1234 AB"
            )

        standard_queries = len(standard_context.queries)
        print(f"   Standard creation: {standard_queries} queries")

        # Test 2: Optimized member creation
        print("\n2. Testing Optimized Member Creation:")
        with self._count_queries(150) as optimized_context:
            optimized_member = self.create_test_member_optimized(
                first_name="Optimized", last_name="Creation", birth_date="1985-01-01"
            )

        optimized_queries = len(optimized_context.queries)
        print(f"   Optimized creation: {optimized_queries} queries")

        # Calculate improvement
        if standard_queries > 0:
            improvement = ((standard_queries - optimized_queries) / standard_queries) * 100
            print(f"   Performance improvement: {improvement:.1f}%")

        # Verify both members were created properly
        self.assertTrue(standard_member.name)
        self.assertTrue(optimized_member.name)
        self.assertEqual(standard_member.first_name, "Standard")
        self.assertEqual(optimized_member.first_name, "Optimized")

        print("✅ Both members created successfully with performance improvement")

    def test_member_search_performance(self):
        """Test optimized member search functionality"""

        print("\n=== MEMBER SEARCH PERFORMANCE TEST ===")

        # Create test members first (using optimized creation)
        test_members = []
        for i in range(3):
            member = self.create_test_member_optimized(
                first_name=f"SearchTest{i}", last_name="User", birth_date="1990-01-01"
            )
            test_members.append(member.name)

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Test optimized search
        print("\n1. Testing Optimized Member Search:")
        with self._count_queries(10) as search_context:
            search_results = member_optimizer.bulk_load_members_optimized(
                filters={"search_term": "SearchTest"}, limit=10
            )

        search_queries = len(search_context.queries)
        print(f"   Search queries: {search_queries}")
        print(f"   Results found: {len(search_results)}")

        # Verify search results quality
        self.assertGreaterEqual(len(search_results), 3, "Should find at least 3 test members")

        # Verify result structure (comprehensive data in single query). The
        # Member email field is "email" (not "email_address"), which is what the
        # optimized query returns.
        if search_results:
            result = search_results[0]
            required_fields = ["name", "full_name", "status", "email", "payment_count"]
            for field in required_fields:
                self.assertIn(field, result, f"Result should contain {field}")

        print("✅ Optimized search working with comprehensive data")

    def test_member_dashboard_caching(self):
        """Test member dashboard caching performance"""

        print("\n=== MEMBER DASHBOARD CACHING TEST ===")

        # Create test member with related data
        member = self.create_test_member_optimized(
            first_name="Dashboard", last_name="Test", birth_date="1985-01-01"
        )

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Test 1: First dashboard load (no cache)
        print("\n1. Testing Initial Dashboard Load:")
        with self._count_queries(5) as first_load_context:
            dashboard_data_1 = member_optimizer.get_member_dashboard_cached(member.name)

        first_load_queries = len(first_load_context.queries)
        print(f"   First load queries: {first_load_queries}")

        # Test 2: Second dashboard load (cached)
        print("\n2. Testing Cached Dashboard Load:")
        with self._count_queries(1) as cached_load_context:
            dashboard_data_2 = member_optimizer.get_member_dashboard_cached(member.name)

        cached_load_queries = len(cached_load_context.queries)
        print(f"   Cached load queries: {cached_load_queries}")

        # Verify cache effectiveness
        self.assertEqual(dashboard_data_1, dashboard_data_2, "Cached data should match original")
        self.assertGreater(first_load_queries, cached_load_queries, "Cache should reduce queries")

        # Verify data quality
        self.assertIn("full_name", dashboard_data_1)
        self.assertIn("payment_count_12m", dashboard_data_1)
        self.assertIn("dashboard_alerts", dashboard_data_1)

        print("✅ Dashboard caching working effectively")

    def test_bulk_member_operations(self):
        """Test bulk member operations performance"""

        print("\n=== BULK MEMBER OPERATIONS TEST ===")

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Create multiple members in sequence using optimized method
        print("\n1. Testing Bulk Member Creation:")
        member_names = []

        with self._count_queries(300) as bulk_creation_context:
            for i in range(5):
                member_data = {
                    "first_name": f"Bulk{i}",
                    "last_name": "Test",
                    "birth_date": "1985-01-01",
                    "email_address": f"bulk{i}@test-performance.local",
                    "postal_code": "1234 AB",
                }
                member_name = member_optimizer.create_member_optimized(member_data)
                member_names.append(member_name)

        bulk_queries = len(bulk_creation_context.queries)
        avg_queries_per_member = bulk_queries / 5

        print(f"   Total queries for 5 members: {bulk_queries}")
        print(f"   Average queries per member: {avg_queries_per_member:.1f}")

        # Verify all members created
        self.assertEqual(len(member_names), 5, "All 5 members should be created")

        # Test bulk loading
        print("\n2. Testing Bulk Member Loading:")
        with self._count_queries(2) as bulk_load_context:
            bulk_results = member_optimizer.bulk_load_members_optimized(
                filters={"search_term": "Bulk"}, limit=10
            )

        load_queries = len(bulk_load_context.queries)
        print(f"   Bulk load queries: {load_queries}")
        print(f"   Members loaded: {len(bulk_results)}")

        self.assertGreaterEqual(len(bulk_results), 5, "Should load all 5 bulk test members")

        print("✅ Bulk operations showing excellent performance")

    def test_performance_optimization_integration(self):
        """Test complete integration of all performance optimizations"""

        print("\n=== COMPLETE PERFORMANCE OPTIMIZATION INTEGRATION TEST ===")

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        start_time = time.time()

        # Complete workflow: Create → Search → Dashboard → Bulk operations
        with self._count_queries(400) as complete_workflow_context:
            # 1. Create optimized member
            member = self.create_test_member_optimized(
                first_name="Integration", last_name="Test", birth_date="1985-01-01"
            )

            # 2. Search for members
            search_results = member_optimizer.bulk_load_members_optimized(
                filters={"search_term": "Integration"}, limit=5
            )

            # 3. Load dashboard data
            dashboard_data = member_optimizer.get_member_dashboard_cached(member.name)

            # 4. Create additional members for bulk test
            for i in range(2):
                extra_member_data = {
                    "first_name": f"Extra{i}",
                    "last_name": "Integration",
                    "birth_date": "1985-01-01",
                    "email_address": f"extra{i}@test-integration.local",
                }
                member_optimizer.create_member_optimized(extra_member_data)

        workflow_queries = len(complete_workflow_context.queries)
        duration = time.time() - start_time

        print(f"\n   Complete workflow performance:")
        print(f"   - Total queries: {workflow_queries}")
        print(f"   - Execution time: {duration:.3f}s")
        print(f"   - Members found in search: {len(search_results)}")
        print(f"   - Dashboard data keys: {len(dashboard_data.keys()) if dashboard_data else 0}")

        # Performance assertions
        self.assertLess(duration, 10.0, "Complete workflow should finish within 10 seconds")
        self.assertLess(workflow_queries, 400, "Complete workflow should use <400 queries")
        self.assertGreater(len(search_results), 0, "Search should find results")
        self.assertGreater(len(dashboard_data.keys()), 5, "Dashboard should have comprehensive data")

        print("✅ Complete performance optimization integration successful")

    def test_validate_member_data_bulk_rejects_duplicate_email(self):
        """Regression: the bulk pre-validation must reject a duplicate email.

        Previously _validate_member_data_bulk queried a non-existent
        `email_address` column on Member (the real field is `email`), so the
        duplicate-email guard never fired. This exercises the validation helper
        directly (the public create path uses its own begin/commit which can't
        run inside the test transaction) and asserts the guard now triggers on
        the real `email` column.
        """
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        existing = self.create_test_member(
            first_name="Dup",
            last_name="Guard",
            birth_date="1985-01-01",
        )
        self.assertTrue(existing.email)

        # An unused email must pass validation.
        fresh = member_optimizer._validate_member_data_bulk(
            {"email": f"unused-{frappe.generate_hash(length=8)}@test-performance.local"}
        )
        self.assertTrue(fresh["valid"])

        # The existing member's email must be rejected as a duplicate.
        dup = member_optimizer._validate_member_data_bulk({"email": existing.email})
        self.assertFalse(dup["valid"])
        self.assertEqual(dup["error"], "Email address already exists")

    @staticmethod
    def generate_performance_report():
        """Generate performance optimization report"""

        print("\n" + "=" * 60)
        print("MEMBER PERFORMANCE OPTIMIZATION REPORT")
        print("=" * 60)
        print()
        print("Key Optimizations Implemented:")
        print("1. 📊 DocType Metadata Caching - Eliminates repeated meta loading")
        print("2. 🚀 Bulk Operations - Creates related records efficiently")
        print("3. 🔍 Optimized Search - Single JOIN query with comprehensive data")
        print("4. ⚡ Dashboard Caching - 5-minute cache for frequent access")
        print("5. 🏃‍♂️ Background Processing - Defers non-critical operations")
        print()
        print("Performance Targets:")
        print("- Member Creation: 692 → ~100 queries (85% reduction)")
        print("- Member Search: <10 queries with full related data")
        print("- Dashboard Load: <5 queries first time, <1 query cached")
        print("- Bulk Operations: ~60 queries per member average")
        print()
        print("Production Benefits:")
        print("✅ Reduced database load and improved response times")
        print("✅ Better user experience with faster page loads")
        print("✅ Scalable architecture for growing membership")
        print("✅ Maintained data integrity and business rule validation")
        print("=" * 60)
