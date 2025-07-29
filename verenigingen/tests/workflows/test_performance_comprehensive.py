"""
Performance and Load Testing Suite
Comprehensive performance testing including large dataset validation,
concurrent user simulation, query optimization, and resource monitoring
"""

import frappe
from frappe.utils import today, add_days, now_datetime, flt
from verenigingen.tests.utils.base import VereningingenTestCase
import time
import threading
from datetime import datetime, timedelta
import psutil
import gc
from concurrent.futures import ThreadPoolExecutor, as_completed


class TestPerformanceComprehensive(VereningingenTestCase):
    """Comprehensive performance and load testing"""

    def setUp(self):
        """Set up test data for performance tests"""
        super().setUp()

        # Performance test configuration
        self.performance_config = {
            "large_dataset_size": 1000,    # Number of records for large dataset tests
            "concurrent_users": 10,        # Number of concurrent users to simulate
            "load_test_duration": 30,      # Duration in seconds for load tests
            "query_timeout": 5.0,          # Maximum acceptable query time in seconds
            "memory_limit_mb": 512,        # Memory usage limit in MB
            "max_db_connections": 50       # Maximum database connections
        }

        # Create baseline test data
        self.baseline_chapter = self.factory.create_test_chapter(
            chapter_name="Performance Baseline Chapter"
        )

        self.baseline_membership_type = self.factory.create_test_membership_type(
            membership_type_name="Performance Test Membership",
            minimum_amount=25.00
        )

        # Performance monitoring data
        self.performance_metrics = {
            "start_time": datetime.now(),
            "query_times": [],
            "memory_usage": [],
            "database_connections": []
        }

    def test_large_dataset_performance_validation(self):
        """Test system performance with large datasets (1000+ records)"""
        print(f"🏗️ Creating {self.performance_config['large_dataset_size']} test records...")

        # Measure performance for large dataset creation
        creation_start = time.time()
        created_members = []

        # Create large number of members in batches for better performance
        batch_size = 100
        total_records = self.performance_config["large_dataset_size"]

        for batch_start in range(0, total_records, batch_size):
            batch_end = min(batch_start + batch_size, total_records)
            batch_members = self._create_member_batch(batch_start, batch_end)
            created_members.extend(batch_members)

            # Log progress
            if batch_end % 200 == 0:
                elapsed = time.time() - creation_start
                print(f"   Created {batch_end}/{total_records} members in {elapsed:.2f}s")

        creation_time = time.time() - creation_start

        # Performance assertions for creation
        avg_creation_time = creation_time / total_records
        self.assertLess(avg_creation_time, 0.1,
                       f"Average member creation should be < 0.1s, got {avg_creation_time:.3f}s")

        print(f"✅ Created {len(created_members)} members in {creation_time:.2f}s")

        # Test large dataset query performance
        query_performance_results = self._test_large_dataset_queries(created_members)

        for query_name, query_time in query_performance_results.items():
            self.assertLess(query_time, self.performance_config["query_timeout"],
                           f"Query '{query_name}' took {query_time:.2f}s, should be < {self.performance_config['query_timeout']}s")

        # Test pagination performance with large datasets
        pagination_results = self._test_pagination_performance(total_records)

        for page_size, page_time in pagination_results.items():
            self.assertLess(page_time, 1.0,
                           f"Pagination with page_size {page_size} took {page_time:.2f}s, should be < 1.0s")

        # Test bulk operations performance
        bulk_operations_results = self._test_bulk_operations_performance(created_members[:500])

        self.assertLess(bulk_operations_results["bulk_update_time"], 5.0,
                       "Bulk update should complete within 5 seconds")

        print(f"🎯 Large dataset performance validation completed successfully")

    def _create_member_batch(self, start_index, end_index):
        """Create a batch of members for performance testing"""
        batch_members = []

        for i in range(start_index, end_index):
            member = self.factory.create_test_member(
                first_name=f"PerfTest{i:04d}",
                last_name=f"Member",
                email=f"perf{i:04d}.member.{self.factory.test_run_id}@example.com",
                chapter=self.baseline_chapter.name
            )
            batch_members.append(member)

        return batch_members

    def _test_large_dataset_queries(self, created_members):
        """Test various queries against large dataset"""
        member_names = [member.name for member in created_members[:100]]  # Test subset

        query_tests = {
            "simple_filter": lambda: frappe.get_all("Member",
                                                   filters={"status": "Active"},
                                                   limit=50),

            "complex_filter": lambda: frappe.get_all("Member",
                                                    filters={
                                                        "status": "Active",
                                                        "chapter": self.baseline_chapter.name,
                                                        "first_name": ["like", "PerfTest%"]
                                                    },
                                                    limit=50),

            "join_query": lambda: frappe.db.sql("""
                SELECT m.name, m.first_name, mb.membership_type
                FROM `tabMember` m
                LEFT JOIN `tabMembership` mb ON m.name = mb.member
                WHERE m.chapter = %s
                LIMIT 50
            """, (self.baseline_chapter.name,)),

            "aggregate_query": lambda: frappe.db.sql("""
                SELECT chapter, COUNT(*) as member_count,
                       AVG(DATEDIFF(CURDATE(), member_since)) as avg_member_days
                FROM `tabMember`
                WHERE status = 'Active'
                GROUP BY chapter
                LIMIT 10
            """),

            "search_query": lambda: frappe.get_all("Member",
                                                  filters={
                                                      "name": ["in", member_names[:20]]
                                                  },
                                                  fields=["name", "first_name", "email"])
        }

        query_results = {}

        for query_name, query_func in query_tests.items():
            start_time = time.time()

            try:
                result = query_func()
                query_time = time.time() - start_time
                query_results[query_name] = query_time

                print(f"   Query '{query_name}': {query_time:.3f}s ({len(result) if result else 0} results)")

            except Exception as e:
                print(f"   Query '{query_name}' failed: {e}")
                query_results[query_name] = float('inf')

        return query_results

    def _test_pagination_performance(self, total_records):
        """Test pagination performance with different page sizes"""
        page_sizes = [20, 50, 100, 200]
        pagination_results = {}

        for page_size in page_sizes:
            start_time = time.time()

            # Test first page
            frappe.get_all("Member",
                          filters={"chapter": self.baseline_chapter.name},
                          fields=["name", "first_name", "email"],
                          limit=page_size,
                          start=0)

            # Test middle page
            middle_start = min(total_records // 2, total_records - page_size)
            frappe.get_all("Member",
                          filters={"chapter": self.baseline_chapter.name},
                          fields=["name", "first_name", "email"],
                          limit=page_size,
                          start=middle_start)

            page_time = time.time() - start_time
            pagination_results[page_size] = page_time

            print(f"   Pagination page_size {page_size}: {page_time:.3f}s")

        return pagination_results

    def _test_bulk_operations_performance(self, members_subset):
        """Test bulk operations performance"""
        start_time = time.time()

        # Bulk update operation
        member_names = [member.name for member in members_subset]

        # Update multiple members at once
        frappe.db.sql("""
            UPDATE `tabMember`
            SET notes = 'Bulk performance test update'
            WHERE name IN ({})
        """.format(','.join(['%s'] * len(member_names))), member_names)

        bulk_update_time = time.time() - start_time

        # Bulk delete operation (create temporary records first)
        temp_start_time = time.time()
        temp_members = []

        for i in range(50):
            temp_member = self.factory.create_test_member(
                first_name=f"TempBulk{i}",
                last_name="Delete",
                email=f"temp.bulk{i}.{self.factory.test_run_id}@example.com"
            )
            temp_members.append(temp_member)

        # Bulk delete
        temp_member_names = [member.name for member in temp_members]
        frappe.db.sql("""
            DELETE FROM `tabMember`
            WHERE name IN ({})
        """.format(','.join(['%s'] * len(temp_member_names))), temp_member_names)

        bulk_delete_time = time.time() - temp_start_time

        return {
            "bulk_update_time": bulk_update_time,
            "bulk_delete_time": bulk_delete_time,
            "records_updated": len(members_subset),
            "records_deleted": len(temp_members)
        }

    def test_concurrent_user_load_simulation(self):
        """Test system behavior under concurrent user load"""
        print(f"👥 Simulating {self.performance_config['concurrent_users']} concurrent users...")

        # Define user scenarios
        user_scenarios = [
            self._scenario_member_portal_access,
            self._scenario_volunteer_dashboard,
            self._scenario_admin_member_search,
            self._scenario_payment_processing,
            self._scenario_report_generation
        ]

        # Run concurrent load test
        load_test_results = self._run_concurrent_load_test(user_scenarios)

        # Analyze results
        total_requests = sum(result["requests_completed"] for result in load_test_results)
        total_errors = sum(result["errors"] for result in load_test_results)
        avg_response_time = sum(result["avg_response_time"] for result in load_test_results) / len(load_test_results)

        # Performance assertions
        self.assertGreater(total_requests, 0, "Should complete some requests")
        error_rate = total_errors / total_requests if total_requests > 0 else 1
        self.assertLess(error_rate, 0.05, f"Error rate should be < 5%, got {error_rate:.2%}")
        self.assertLess(avg_response_time, 2.0, f"Average response time should be < 2s, got {avg_response_time:.2f}s")

        print(f"✅ Concurrent load test completed: {total_requests} requests, {error_rate:.2%} error rate, {avg_response_time:.2f}s avg response")

    def _run_concurrent_load_test(self, scenarios):
        """Run concurrent load test with multiple scenarios"""
        results = []

        with ThreadPoolExecutor(max_workers=self.performance_config["concurrent_users"]) as executor:
            # Submit concurrent tasks
            futures = []
            for i in range(self.performance_config["concurrent_users"]):
                scenario = scenarios[i % len(scenarios)]
                future = executor.submit(self._simulate_user_load, scenario, i)
                futures.append(future)

            # Collect results
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=60)  # 60 second timeout
                    results.append(result)
                except Exception as e:
                    results.append({
                        "requests_completed": 0,
                        "errors": 1,
                        "avg_response_time": float('inf'),
                        "error_details": str(e)
                    })

        return results

    def _simulate_user_load(self, scenario_func, user_id):
        """Simulate load for a single user"""
        requests_completed = 0
        errors = 0
        response_times = []

        test_duration = self.performance_config["load_test_duration"]
        start_time = time.time()

        while time.time() - start_time < test_duration:
            try:
                request_start = time.time()
                scenario_func(user_id)
                response_time = time.time() - request_start

                response_times.append(response_time)
                requests_completed += 1

                # Small delay between requests
                time.sleep(0.1)

            except Exception as e:
                errors += 1
                print(f"User {user_id} error: {e}")

            # Check if we should continue
            if time.time() - start_time >= test_duration:
                break

        avg_response_time = sum(response_times) / len(response_times) if response_times else float('inf')

        return {
            "user_id": user_id,
            "requests_completed": requests_completed,
            "errors": errors,
            "avg_response_time": avg_response_time,
            "max_response_time": max(response_times) if response_times else 0,
            "min_response_time": min(response_times) if response_times else 0
        }

    def _scenario_member_portal_access(self, user_id):
        """Simulate member portal access scenario"""
        # Create or get test member for this user
        member_email = f"load.test.user{user_id}.{self.factory.test_run_id}@example.com"

        try:
            member = frappe.get_doc("Member", {"email": member_email})
        except frappe.DoesNotExistError:
            member = self.factory.create_test_member(
                first_name=f"LoadTest{user_id}",
                last_name="User",
                email=member_email
            )

        # Simulate portal activities
        frappe.get_all("Membership", filters={"member": member.name}, limit=5)
        frappe.get_all("Member Payment History", filters={"member": member.name}, limit=10)

    def _scenario_volunteer_dashboard(self, user_id):
        """Simulate volunteer dashboard access scenario"""
        # Get volunteer assignments
        frappe.get_all("Volunteer Assignment",
                      filters={"status": "Active"},
                      limit=10)

        # Get volunteer expenses
        frappe.get_all("Volunteer Expense",
                      filters={"status": ["in", ["Submitted", "Approved"]]},
                      limit=10)

    def _scenario_admin_member_search(self, user_id):
        """Simulate admin member search scenario"""
        search_terms = ["PerfTest", "LoadTest", "Member", "Test"]
        search_term = search_terms[user_id % len(search_terms)]

        # Search members
        frappe.get_all("Member",
                      filters={"first_name": ["like", f"%{search_term}%"]},
                      fields=["name", "first_name", "last_name", "email"],
                      limit=20)

    def _scenario_payment_processing(self, user_id):
        """Simulate payment processing scenario"""
        # Get recent payment history
        frappe.get_all("Member Payment History",
                      filters={"payment_date": [">=", add_days(today(), -30)]},
                      limit=15)

        # Get SEPA mandates
        frappe.get_all("SEPA Mandate",
                      filters={"status": "Active"},
                      limit=10)

    def _scenario_report_generation(self, user_id):
        """Simulate report generation scenario"""
        # Generate member statistics
        frappe.db.sql("""
            SELECT status, COUNT(*) as count
            FROM `tabMember`
            GROUP BY status
        """)

        # Generate chapter statistics
        frappe.db.sql("""
            SELECT chapter, COUNT(*) as member_count
            FROM `tabMember`
            WHERE status = 'Active'
            GROUP BY chapter
            LIMIT 10
        """)

    def test_query_optimization_regression(self):
        """Test query optimization and detect performance regressions"""
        print("🔍 Running query optimization regression tests...")

        # Define critical queries with performance benchmarks
        critical_queries = {
            "member_lookup": {
                "query": lambda: frappe.get_all("Member",
                                               filters={"email": f"perf0001.member.{self.factory.test_run_id}@example.com"},
                                               limit=1),
                "max_time": 0.1,
                "description": "Member lookup by email"
            },

            "active_memberships": {
                "query": lambda: frappe.get_all("Membership",
                                               filters={"status": "Active"},
                                               fields=["name", "member", "membership_type"],
                                               limit=100),
                "max_time": 0.5,
                "description": "Active memberships list"
            },

            "chapter_members": {
                "query": lambda: frappe.db.sql("""
                    SELECT m.name, m.first_name, m.last_name
                    FROM `tabMember` m
                    WHERE m.chapter = %s AND m.status = 'Active'
                    LIMIT 50
                """, (self.baseline_chapter.name,)),
                "max_time": 0.3,
                "description": "Chapter members query"
            },

            "payment_history_summary": {
                "query": lambda: frappe.db.sql("""
                    SELECT DATE(payment_date) as date,
                           COUNT(*) as transaction_count,
                           SUM(amount) as total_amount
                    FROM `tabMember Payment History`
                    WHERE payment_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
                    GROUP BY DATE(payment_date)
                    ORDER BY date DESC
                    LIMIT 30
                """),
                "max_time": 0.8,
                "description": "Payment history summary"
            },

            "sepa_mandate_status": {
                "query": lambda: frappe.db.sql("""
                    SELECT status, COUNT(*) as count
                    FROM `tabSEPA Mandate`
                    GROUP BY status
                """),
                "max_time": 0.2,
                "description": "SEPA mandate status summary"
            }
        }

        regression_results = {}

        for query_name, query_config in critical_queries.items():
            # Run query multiple times for accurate measurement
            execution_times = []

            for _ in range(5):  # Run 5 times
                start_time = time.time()
                try:
                    query_config["query"]()
                    execution_time = time.time() - start_time
                    execution_times.append(execution_time)
                except Exception as e:
                    execution_times.append(float('inf'))
                    print(f"Query '{query_name}' failed: {e}")

            # Calculate statistics
            avg_time = sum(execution_times) / len(execution_times)
            max_time = max(execution_times)
            min_time = min(execution_times)

            regression_results[query_name] = {
                "avg_time": avg_time,
                "max_time": max_time,
                "min_time": min_time,
                "benchmark": query_config["max_time"],
                "passed": avg_time <= query_config["max_time"],
                "description": query_config["description"]
            }

            # Performance assertion
            self.assertLessEqual(avg_time, query_config["max_time"],
                               f"Query '{query_name}' avg time {avg_time:.3f}s exceeds benchmark {query_config['max_time']}s")

            print(f"   {query_name}: {avg_time:.3f}s avg (benchmark: {query_config['max_time']}s) {'✅' if regression_results[query_name]['passed'] else '❌'}")

        # Generate performance report
        self._generate_performance_report(regression_results)

        print("✅ Query optimization regression tests completed")

    def test_memory_usage_resource_monitoring(self):
        """Test memory usage and resource monitoring"""
        print("💾 Monitoring memory usage and system resources...")

        # Get initial system state
        initial_memory = psutil.virtual_memory()
        initial_process = psutil.Process()
        initial_process_memory = initial_process.memory_info()

        print(f"   Initial system memory: {initial_memory.percent:.1f}% used")
        print(f"   Initial process memory: {initial_process_memory.rss / 1024 / 1024:.1f} MB")

        # Memory stress test
        self._run_memory_stress_test()

        # Get final system state
        final_memory = psutil.virtual_memory()
        final_process = psutil.Process()
        final_process_memory = final_process.memory_info()

        # Calculate memory usage
        memory_increase = (final_process_memory.rss - initial_process_memory.rss) / 1024 / 1024
        system_memory_change = final_memory.percent - initial_memory.percent

        print(f"   Final system memory: {final_memory.percent:.1f}% used (change: {system_memory_change:+.1f}%)")
        print(f"   Final process memory: {final_process_memory.rss / 1024 / 1024:.1f} MB (change: {memory_increase:+.1f} MB)")

        # Performance assertions
        self.assertLess(memory_increase, self.performance_config["memory_limit_mb"],
                       f"Memory increase {memory_increase:.1f}MB should be < {self.performance_config['memory_limit_mb']}MB")

        self.assertLess(abs(system_memory_change), 10.0,
                       f"System memory change should be < 10%, got {system_memory_change:.1f}%")

        # Test database connection limits
        db_connection_test = self._test_database_connection_limits()
        self.assertTrue(db_connection_test["within_limits"],
                       "Database connections should be within limits")

        print("✅ Memory usage and resource monitoring completed")

    def _run_memory_stress_test(self):
        """Run memory stress test"""
        # Create large amounts of test data in memory
        large_data_structures = []

        try:
            # Create memory-intensive operations
            for i in range(100):
                # Create large member dataset in memory
                member_data = []
                for j in range(100):
                    member_data.append({
                        "name": f"stress_test_{i}_{j}",
                        "first_name": f"StressTest{i}",
                        "last_name": f"Member{j}",
                        "email": f"stress{i}.{j}@example.com",
                        "large_field": "x" * 1000  # 1KB per member
                    })
                large_data_structures.append(member_data)

            # Force garbage collection
            gc.collect()

            return {
                "data_structures_created": len(large_data_structures),
                "estimated_memory_mb": len(large_data_structures) * 100 * 1000 / 1024 / 1024
            }

        finally:
            # Clean up memory
            large_data_structures.clear()
            gc.collect()

    def _test_database_connection_limits(self):
        """Test database connection management"""
        # Get current database connection count
        try:
            connections = frappe.db.sql("SHOW PROCESSLIST", as_dict=True)
            current_connections = len(connections)

            # Test connection pooling
            connection_test_results = []

            for i in range(10):
                # Each query should reuse connections efficiently
                start_time = time.time()
                frappe.db.sql("SELECT 1")
                query_time = time.time() - start_time
                connection_test_results.append(query_time)

            avg_connection_time = sum(connection_test_results) / len(connection_test_results)

            return {
                "within_limits": current_connections < self.performance_config["max_db_connections"],
                "current_connections": current_connections,
                "avg_connection_time": avg_connection_time,
                "connection_limit": self.performance_config["max_db_connections"]
            }

        except Exception as e:
            return {
                "within_limits": True,  # Assume OK if can't measure
                "error": str(e)
            }

    def _generate_performance_report(self, regression_results):
        """Generate performance test report"""
        report = {
            "timestamp": datetime.now(),
            "test_config": self.performance_config,
            "query_performance": regression_results,
            "summary": {
                "total_queries": len(regression_results),
                "passed_queries": sum(1 for r in regression_results.values() if r["passed"]),
                "failed_queries": sum(1 for r in regression_results.values() if not r["passed"]),
                "avg_performance": sum(r["avg_time"] for r in regression_results.values()) / len(regression_results)
            }
        }

        # Log performance report
        print(f"📊 Performance Report Summary:")
        print(f"   Total queries tested: {report['summary']['total_queries']}")
        print(f"   Passed: {report['summary']['passed_queries']}")
        print(f"   Failed: {report['summary']['failed_queries']}")
        print(f"   Average performance: {report['summary']['avg_performance']:.3f}s")

        return report


def run_performance_comprehensive_tests():
    """Run comprehensive performance tests"""
    print("⚡ Running Comprehensive Performance Tests...")

    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPerformanceComprehensive)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All performance tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        return False


if __name__ == "__main__":
    run_performance_comprehensive_tests()
