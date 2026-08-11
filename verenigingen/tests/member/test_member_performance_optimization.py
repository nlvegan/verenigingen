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

        Patches the INSTANCE, not the class. This used to assign
        ``frappe.db.__class__.sql``, which an instance attribute silently shadows --
        and one gets left behind: tests/integration/test_query_optimization_suite.py
        does ``original_sql = frappe.db.sql`` / ``frappe.db.sql = counting_sql`` and
        then "restores" with ``frappe.db.sql = original_sql``, which re-assigns the
        instance attribute instead of deleting it. After that module runs once in a
        process, ``frappe.db`` carries an instance ``sql`` forever, every later
        class-level patch is invisible, and this counter silently records ZERO
        queries.

        That is what made test_member_dashboard_caching fail in CI and never locally:
        with nothing counted, `first_load > cached_load` was `0 > 0`. It also means
        every upper-bound assertion here passed vacuously in any shard where that
        module ran first -- `assertLessEqual(0, 300)` is always true. An instance
        attribute always wins lookup, so patching at that level is immune to both.
        """
        counter = _QueryCounter()
        had_own_sql = "sql" in frappe.db.__dict__
        orig_sql = frappe.db.sql

        def _sql_with_count(*args, **kwargs):
            ret = orig_sql(*args, **kwargs)
            counter.queries.append(str(args[0]) if args else "")
            return ret

        try:
            frappe.db.sql = _sql_with_count
            yield counter
        finally:
            # Delete rather than re-assign when there was no instance attribute to
            # begin with -- re-assigning is exactly the bug described above.
            if had_own_sql:
                frappe.db.sql = orig_sql
            else:
                del frappe.db.sql
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

        # Control this test's own precondition instead of relying on setUp's global
        # clear. setUp clears every `member_dashboard:*` key, which is necessary but
        # provably not sufficient: after that clear was fixed, CI STILL reached the
        # first load with a warm entry for this member. Member docnames are reissued
        # after a rollback (the naming series is transactional, Redis is not), so a
        # docname can acquire a cache entry from something that ran between setUp and
        # here. Clearing this member's own key immediately before measuring makes the
        # measurement independent of whatever that is.
        cache_key = f"member_dashboard:{member.name}"
        frappe.cache().delete_key(cache_key)
        self.assertIsNone(
            frappe.cache().get_value(cache_key),
            "precondition failed: this member's dashboard cache entry survived an "
            "explicit delete_key() -- the cache layer is not behaving as assumed",
        )

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

        # Verify cache effectiveness.
        #
        # Assert the two properties directly rather than comparing the counts to each
        # other. `first > cached` was a 1-vs-0 margin, so a single stale cache entry
        # for this member's docname turned it into `0 > 0` and failed -- which is
        # exactly what happened intermittently in CI, because clear_all_member_caches()
        # was a no-op (see test_clear_all_member_caches_actually_clears) and a
        # rolled-back earlier test hands its docname to the next one.
        self.assertEqual(dashboard_data_1, dashboard_data_2, "Cached data should match original")
        self.assertGreaterEqual(
            first_load_queries,
            1,
            "Uncached load must query the database. The cache entry was explicitly "
            "deleted and asserted absent immediately above, so if this fails the cause "
            "is NOT a stale cache: either _count_queries is not observing "
            "frappe.db.sql, or something repopulated the key in between.",
        )
        self.assertEqual(cached_load_queries, 0, "Cached load must not query the database")

        # Verify data quality
        self.assertIn("full_name", dashboard_data_1)
        self.assertIn("payment_count_12m", dashboard_data_1)
        self.assertIn("dashboard_alerts", dashboard_data_1)

        print("✅ Dashboard caching working effectively")

    def test_clear_all_member_caches_actually_clears(self):
        """clear_all_member_caches() must delete the keys it targets.

        It used to do `for key in cache.get_keys("member_dashboard:*"):
        cache.delete_value(key)`. get_keys() returns keys with the site namespace
        ALREADY applied (`_<hash>|member_dashboard:X`), and delete_value() defaults to
        make_keys=True and applies it again, so every delete targeted
        `_<hash>|_<hash>|member_dashboard:X` and removed nothing. The clear was a
        silent no-op.

        That is not merely untidy: this module's setUp calls it to guarantee a cold
        cache, and Member docnames come from a naming series that IS rolled back with
        the test transaction while Redis is not -- so a rolled-back test hands both its
        docname and its surviving dashboard cache entry to the next test, whose
        "uncached" load is then a cache hit. That is the intermittent CI failure of
        test_member_dashboard_caching.

        The same double-prefix trap is documented and already fixed in
        payment_utils.py and financial_utils.py; frappe's own delete_keys() gets it
        right by passing make_keys=False.
        """
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        cache = frappe.cache()
        probe_key = f"member_dashboard:PROBE-{frappe.generate_hash(length=8)}"
        # TTL so a regression leaks nothing permanently: if the clear stops working,
        # the probe expires on its own instead of living in Redis forever.
        cache.set_value(probe_key, '{"probe": true}', expires_in_sec=60)
        self.assertIsNotNone(cache.get_value(probe_key), "fixture invalid: probe key not set")

        member_optimizer.clear_all_member_caches()

        self.assertIsNone(
            cache.get_value(probe_key),
            "clear_all_member_caches() left the key in place -- the delete is double-prefixed",
        )

    def test_query_counter_survives_an_instance_level_sql_attribute(self):
        """_count_queries must still count when frappe.db carries its own `sql`.

        This is the root cause of the CI-only failure of test_member_dashboard_caching.
        `frappe.db.sql` is normally a CLASS attribute, and a helper that "restores" it
        with `frappe.db.sql = original` (rather than deleting) leaves a permanent
        INSTANCE attribute behind -- tests/integration/test_query_optimization_suite.py
        did exactly that. An instance attribute wins attribute lookup, so a counter
        patching `frappe.db.__class__.sql` afterwards observed nothing and recorded
        zero queries, in any shard where that module happened to run first.

        Zero counted queries makes every upper-bound assertion pass vacuously and
        turns `assertGreater(first_load, cached_load)` into `0 > 0`.
        """
        # Simulate the polluted state left behind by the other module.
        frappe.db.sql = frappe.db.sql
        self.assertIn("sql", frappe.db.__dict__, "fixture invalid: no instance attribute set")
        try:
            with self._count_queries(50) as ctx:
                frappe.db.sql("SELECT 1")
            self.assertGreaterEqual(
                len(ctx.queries), 1, "counter must observe queries despite the instance attribute"
            )
        finally:
            frappe.db.__dict__.pop("sql", None)

    def test_bulk_member_operations(self):
        """Test bulk member operations performance"""

        print("\n=== BULK MEMBER OPERATIONS TEST ===")

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Create multiple members in sequence using optimized method
        print("\n1. Testing Bulk Member Creation:")
        member_names = []

        # Warm DocType meta / schema caches before counting, for the same reason
        # test_standard_vs_optimized_member_creation does: the first creation in a
        # cold process pays one-time information_schema + tabDocType/tabDocField
        # introspection that dwarfs the actual creation cost. This test runs FIRST in
        # the class (methods run alphabetically), so it always paid that cost when the
        # module ran alone -- 4513 queries against a budget of 300 -- while passing in
        # CI only because other modules had already warmed the cache in the same
        # process. A budget assertion that depends on what ran before it is not
        # measuring anything.
        member_optimizer.create_member_optimized(
            {
                "first_name": "BulkWarmup",
                "last_name": f"T{frappe.generate_hash(length=6)}",
                "birth_date": "1985-01-01",
                "email_address": f"bulk-warmup-{frappe.generate_hash(length=8)}@test-performance.local",
                "postal_code": "1234 AB",
            }
        )

        # 100, not 300. With the warm-up above the block measures 55 (11 per member),
        # so a 300 budget could not detect even a 4x regression. Note what this path
        # does NOT cover: `email_address` is not a Member field, so member.email stays
        # empty and Member.after_insert skips Customer creation entirely -- these 11
        # queries are a member creation with the customer branch dormant. Correcting
        # that key would legitimately raise the count; raise the budget deliberately if
        # so, rather than widening it pre-emptively now.
        with self._count_queries(100) as bulk_creation_context:
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

        # A Member's after_insert hook creates a Customer named after the member's
        # full_name, and Customer rows are COMMITTED -- EnhancedTestCase's per-test
        # rollback does not remove them. With the fixed names this test used
        # ("Integration Test"), the second run on any database died with
        # IntegrityError (1062, "Duplicate entry 'Integration Test' for key
        # 'PRIMARY'"). It passed in CI only because CI starts from an empty database,
        # so the test could never fail there and never pass twice anywhere else.
        unique = frappe.generate_hash(length=8)
        search_term = f"Integration{unique}"

        # Warm DocType meta / schema caches before counting -- see
        # test_bulk_member_operations for why a cold process otherwise spends
        # thousands of queries on one-time introspection inside the counted block.
        self.create_test_member_optimized(
            first_name="IntegrationWarmup", last_name=f"T{unique}", birth_date="1985-01-01"
        )

        # Timed from HERE, after the warm-up. The warm-up is the expensive cold-cache
        # path (~4500 queries on a cold process), so starting the clock before it would
        # put the one-time introspection cost inside the 10-second wall-clock assertion
        # below -- measuring the process's startup state rather than the workflow.
        start_time = time.time()

        # Complete workflow: Create → Search → Dashboard → Bulk operations
        with self._count_queries(400) as complete_workflow_context:
            # 1. Create optimized member
            member = self.create_test_member_optimized(
                first_name=search_term, last_name="Test", birth_date="1985-01-01"
            )

            # 2. Search for members
            search_results = member_optimizer.bulk_load_members_optimized(
                filters={"search_term": search_term}, limit=5
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
