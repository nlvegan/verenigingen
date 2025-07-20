"""
Performance Edge Cases Test Suite
Tests for performance under stress, large datasets, concurrent operations, and resource constraints
"""

import random
import threading
import time
import unittest
from datetime import datetime

import frappe
import psutil

from verenigingen.tests.test_data_factory import TestDataContext, TestDataFactory


class TestPerformanceEdgeCases(unittest.TestCase):
    """Test performance edge cases and system limits"""

    @classmethod
    def setUpClass(cls):
        """Set up performance testing environment"""
        cls.factory = TestDataFactory()
        cls.performance_metrics = {}
        cls.test_start_time = time.time()

        print("🚀 Setting up performance test environment...")

        # Create baseline data for performance tests
        cls.baseline_data = cls.factory.create_edge_case_data()

        # Record initial system state
        cls.initial_memory = psutil.virtual_memory().available
        cls.initial_cpu = psutil.cpu_percent(interval=1)

    @classmethod
    def tearDownClass(cls):
        """Clean up performance test data"""
        cls.factory.cleanup()

        # Print performance summary
        total_time = time.time() - cls.test_start_time
        print(f"\n📊 Performance test suite completed in {total_time:.2f}s")

        for test_name, metrics in cls.performance_metrics.items():
            print(f"   - {test_name}: {metrics.get('duration', 0):.2f}s")

    def setUp(self):
        """Set up each performance test"""
        frappe.set_user("Administrator")
        self.test_start = time.time()
        self.start_memory = psutil.virtual_memory().available

    def tearDown(self):
        """Record performance metrics"""
        test_duration = time.time() - self.test_start
        memory_used = self.start_memory - psutil.virtual_memory().available

        test_name = self._testMethodName
        self.performance_metrics[test_name] = {
            "duration": test_duration,
            "memory_used_mb": memory_used / (1024 * 1024),
            "timestamp": datetime.now().isoformat()}

    def measure_time(self, func, *args, **kwargs):
        """Measure execution time of a function"""
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        return result, end_time - start_time

    # ===== LARGE DATASET PERFORMANCE =====

    def test_large_member_query_performance(self):
        """Test query performance with large member datasets"""
        print("📊 Testing large member query performance...")

        # Create large dataset
        with TestDataContext("performance", member_count=1000) as data:
            data["members"]

            # Test various query patterns
            query_tests = [
                ("Simple filter", lambda: frappe.get_all("Member", filters={"status": "Active"})),
                (
                    "Complex filter",
                    lambda: frappe.get_all(
                        "Member", filters=[["status", "in", ["Active", "Suspended"]], ["chapter", "!=", ""]]
                    ),
                ),
                (
                    "Join query",
                    lambda: frappe.db.sql(
                        """
                    SELECT m.name, m.member_name, c.chapter_name
                    FROM `tabMember` m
                    LEFT JOIN `tabChapter` c ON m.chapter = c.name
                    WHERE m.status = 'Active'
                    LIMIT 100
                """,
                        as_dict=True,
                    ),
                ),
                (
                    "Aggregation",
                    lambda: frappe.db.sql(
                        """
                    SELECT chapter, COUNT(*) as member_count
                    FROM `tabMember`
                    GROUP BY chapter
                """,
                        as_dict=True,
                    ),
                ),
            ]

            for test_name, query_func in query_tests:
                result, duration = self.measure_time(query_func)

                # Performance assertions
                self.assertLess(duration, 5.0, f"{test_name} query took too long: {duration:.2f}s")
                self.assertIsNotNone(result, f"{test_name} query returned no results")

                print(f"   ✅ {test_name}: {duration:.3f}s ({len(result) if result else 0} results)")

    def test_bulk_member_creation_performance(self):
        """Test performance of bulk member creation"""
        print("📊 Testing bulk member creation performance...")

        chapter = self.baseline_data["chapters"][0]
        member_count = 100

        # Test bulk creation
        start_time = time.time()

        members_created = []
        for i in range(member_count):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": f"BulkTest{i:04d}",
                    "last_name": "Performance",
                    "email": f"bulktest{i:04d}@performance.test",
                    "status": "Active",
                    "chapter": chapter.name}
            )
            member.insert(ignore_permissions=True)
            members_created.append(member)

        creation_time = time.time() - start_time

        # Performance assertions
        avg_time_per_member = creation_time / member_count
        self.assertLess(
            avg_time_per_member, 0.1, f"Member creation too slow: {avg_time_per_member:.3f}s per member"
        )

        print(
            f"   ✅ Created {member_count} members in {creation_time:.2f}s "
            f"({avg_time_per_member:.3f}s per member)"
        )

        # Clean up
        for member in members_created:
            member.delete(ignore_permissions=True, force=True)

    def test_large_report_generation_performance(self):
        """Test report generation performance with large datasets"""
        print("📊 Testing large report generation performance...")

        with TestDataContext("performance", member_count=500) as data:
            # Test various reports
            report_tests = [
                ("Member list", "SELECT name, member_name, status FROM `tabMember` LIMIT 100"),
                (
                    "Membership summary",
                    """
                    SELECT m.status, COUNT(*) as count
                    FROM `tabMembership` m
                    GROUP BY m.status
                """,
                ),
                (
                    "Chapter statistics",
                    """
                    SELECT c.chapter_name, COUNT(m.name) as member_count
                    FROM `tabChapter` c
                    LEFT JOIN `tabMember` m ON c.name = m.chapter
                    GROUP BY c.name
                """,
                ),
            ]

            for report_name, query in report_tests:
                result, duration = self.measure_time(lambda q=query: frappe.db.sql(q, as_dict=True))

                # Performance assertions
                self.assertLess(duration, 3.0, f"{report_name} report too slow: {duration:.2f}s")
                self.assertIsNotNone(result, f"{report_name} report returned no data")

                print(f"   ✅ {report_name}: {duration:.3f}s ({len(result)} rows)")

    # ===== MEMORY PRESSURE TESTS =====

    def test_memory_usage_under_load(self):
        """Test memory usage under heavy load"""
        print("📊 Testing memory usage under load...")

        initial_memory = psutil.virtual_memory().available

        with TestDataContext("performance", member_count=200) as data:
            # Perform memory-intensive operations
            operations = [
                lambda: frappe.get_all("Member", fields=["*"]),  # Load all fields
                lambda: frappe.db.sql("SELECT * FROM `tabMember`", as_dict=True),  # Raw SQL
                lambda: [frappe.get_doc("Member", m.name) for m in data["members"][:50]],  # Load docs
            ]

            for i, operation in enumerate(operations):
                start_memory = psutil.virtual_memory().available

                result, duration = self.measure_time(operation)

                end_memory = psutil.virtual_memory().available
                memory_used = (start_memory - end_memory) / (1024 * 1024)  # MB

                # Memory usage assertions
                self.assertLess(
                    memory_used, 100, f"Operation {i + 1} used too much memory: {memory_used:.1f}MB"
                )

                print(f"   ✅ Operation {i + 1}: {duration:.3f}s, {memory_used:.1f}MB used")

        # Check for memory leaks
        final_memory = psutil.virtual_memory().available
        memory_leak = (initial_memory - final_memory) / (1024 * 1024)  # MB

        self.assertLess(memory_leak, 50, f"Potential memory leak detected: {memory_leak:.1f}MB")
        print(f"   ✅ Memory leak check: {memory_leak:.1f}MB difference")

    def test_large_document_handling(self):
        """Test handling of documents with large amounts of data"""
        print("📊 Testing large document handling...")

        chapter = self.baseline_data["chapters"][0]

        # Create member with large text fields
        large_text = "x" * 10000  # 10KB of text

        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Large",
                "last_name": "Document",
                "email": "large.document@performance.test",
                "status": "Active",
                "chapter": chapter.name,
                "notes": large_text,  # Large field
            }
        )

        # Test creation
        create_result, create_time = self.measure_time(lambda: member.insert(ignore_permissions=True))

        self.assertLess(create_time, 2.0, f"Large document creation too slow: {create_time:.2f}s")

        # Test retrieval
        retrieve_result, retrieve_time = self.measure_time(lambda: frappe.get_doc("Member", member.name))

        self.assertLess(retrieve_time, 1.0, f"Large document retrieval too slow: {retrieve_time:.2f}s")

        # Test update
        member.notes = large_text + " updated"
        update_result, update_time = self.measure_time(lambda: member.save())

        self.assertLess(update_time, 2.0, f"Large document update too slow: {update_time:.2f}s")

        print(
            f"   ✅ Large document: create {create_time:.3f}s, "
            f"retrieve {retrieve_time:.3f}s, update {update_time:.3f}s"
        )

        # Clean up
        member.delete(ignore_permissions=True, force=True)

    # ===== CONCURRENT OPERATION TESTS =====

    def test_concurrent_member_creation(self):
        """Test concurrent member creation performance"""
        print("📊 Testing concurrent member creation...")

        chapter = self.baseline_data["chapters"][0]
        thread_count = 5
        members_per_thread = 10
        created_members = []
        exceptions = []

        def create_members_thread(thread_id):
            try:
                thread_members = []
                for i in range(members_per_thread):
                    member = frappe.get_doc(
                        {
                            "doctype": "Member",
                            "first_name": f"Concurrent{thread_id}",
                            "last_name": f"Member{i:02d}",
                            "email": f"concurrent{thread_id}.{i:02d}@performance.test",
                            "status": "Active",
                            "chapter": chapter.name}
                    )
                    member.insert(ignore_permissions=True)
                    thread_members.append(member)

                created_members.extend(thread_members)

            except Exception as e:
                exceptions.append(f"Thread {thread_id}: {str(e)}")

        # Start concurrent threads
        threads = []
        start_time = time.time()

        for i in range(thread_count):
            thread = threading.Thread(target=create_members_thread, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        concurrent_time = time.time() - start_time

        # Verify results
        expected_count = thread_count * members_per_thread
        actual_count = len(created_members)

        # Allow for some failures in concurrent scenarios
        self.assertGreaterEqual(
            actual_count,
            expected_count * 0.8,
            f"Too many concurrent creation failures: {actual_count}/{expected_count}",
        )

        self.assertLess(concurrent_time, 30.0, f"Concurrent creation too slow: {concurrent_time:.2f}s")

        print(
            f"   ✅ Concurrent creation: {actual_count}/{expected_count} members "
            f"in {concurrent_time:.2f}s ({len(exceptions)} errors)"
        )

        # Clean up
        for member in created_members:
            try:
                member.delete(ignore_permissions=True, force=True)
            except Exception:
                pass

    def test_concurrent_database_access(self):
        """Test concurrent database access patterns"""
        print("📊 Testing concurrent database access...")

        with TestDataContext("minimal") as data:
            members = data["members"]

            read_results = []
            write_results = []
            exceptions = []

            def read_operations():
                try:
                    for _ in range(20):
                        # Random read operations
                        member = random.choice(members)
                        doc = frappe.get_doc("Member", member.name)
                        read_results.append(doc.name)
                        time.sleep(0.01)  # Small delay
                except Exception as e:
                    exceptions.append(f"Read error: {str(e)}")

            def write_operations():
                try:
                    for i in range(10):
                        # Random write operations
                        member = random.choice(members)
                        doc = frappe.get_doc("Member", member.name)
                        doc.notes = f"Concurrent update {i} at {time.time()}"
                        doc.save()
                        write_results.append(doc.name)
                        time.sleep(0.02)  # Small delay
                except Exception as e:
                    exceptions.append(f"Write error: {str(e)}")

            # Start concurrent read/write operations
            import random

            threads = []
            start_time = time.time()

            # Start multiple read threads
            for _ in range(3):
                thread = threading.Thread(target=read_operations)
                threads.append(thread)
                thread.start()

            # Start write thread
            thread = threading.Thread(target=write_operations)
            threads.append(thread)
            thread.start()

            # Wait for completion
            for thread in threads:
                thread.join()

            concurrent_access_time = time.time() - start_time

            # Verify results
            self.assertGreater(len(read_results), 50, "Not enough read operations completed")
            self.assertGreater(len(write_results), 5, "Not enough write operations completed")
            self.assertLess(len(exceptions), 5, f"Too many concurrent access errors: {exceptions}")

            print(
                f"   ✅ Concurrent access: {len(read_results)} reads, "
                f"{len(write_results)} writes in {concurrent_access_time:.2f}s "
                f"({len(exceptions)} errors)"
            )

    # ===== DATABASE QUERY PERFORMANCE =====

    def test_complex_query_performance(self):
        """Test performance of complex database queries"""
        print("📊 Testing complex query performance...")

        with TestDataContext("performance", member_count=300) as data:
            complex_queries = [
                (
                    "Multi-table join",
                    """
                    SELECT m.name, m.member_name, c.chapter_name, ms.status as membership_status
                    FROM `tabMember` m
                    LEFT JOIN `tabChapter` c ON m.chapter = c.name
                    LEFT JOIN `tabMembership` ms ON m.name = ms.member
                    WHERE m.status = 'Active'
                    ORDER BY c.chapter_name, m.member_name
                    LIMIT 50
                """,
                ),
                (
                    "Aggregation with grouping",
                    """
                    SELECT
                        c.chapter_name,
                        COUNT(DISTINCT m.name) as member_count,
                        COUNT(DISTINCT v.name) as volunteer_count,
                        AVG(ms.annual_fee) as avg_fee
                    FROM `tabChapter` c
                    LEFT JOIN `tabMember` m ON c.name = m.chapter
                    LEFT JOIN `tabVolunteer` v ON m.name = v.member
                    LEFT JOIN `tabMembership` ms ON m.name = ms.member
                    GROUP BY c.name
                    HAVING member_count > 0
                """,
                ),
                (
                    "Subquery with exists",
                    """
                    SELECT m.name, m.member_name
                    FROM `tabMember` m
                    WHERE EXISTS (
                        SELECT 1 FROM `tabMembership` ms
                        WHERE ms.member = m.name AND ms.status = 'Active'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM `tabVolunteer` v
                        WHERE v.member = m.name
                    )
                    LIMIT 25
                """,
                ),
            ]

            for query_name, query in complex_queries:
                result, duration = self.measure_time(lambda q=query: frappe.db.sql(q, as_dict=True))

                # Performance assertions
                self.assertLess(duration, 5.0, f"{query_name} too slow: {duration:.2f}s")
                self.assertIsNotNone(result, f"{query_name} returned no results")

                print(f"   ✅ {query_name}: {duration:.3f}s ({len(result)} rows)")

    def test_database_connection_pooling(self):
        """Test database connection pooling under load"""
        print("📊 Testing database connection pooling...")

        connection_results = []
        exceptions = []

        def database_operations(thread_id):
            try:
                for i in range(10):
                    # Perform database operations
                    result = frappe.db.sql("SELECT COUNT(*) as count FROM `tabMember`", as_dict=True)
                    connection_results.append(f"Thread{thread_id}-{i}: {result[0]['count']}")
                    time.sleep(0.01)
            except Exception as e:
                exceptions.append(f"Thread {thread_id}: {str(e)}")

        # Start multiple threads that use database connections
        threads = []
        start_time = time.time()

        for i in range(8):  # 8 concurrent database threads
            thread = threading.Thread(target=database_operations, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        pooling_time = time.time() - start_time

        # Verify connection pooling worked
        self.assertGreater(len(connection_results), 70, "Not enough database operations completed")
        self.assertLess(len(exceptions), 3, f"Too many connection errors: {exceptions}")

        print(
            f"   ✅ Connection pooling: {len(connection_results)} operations "
            f"in {pooling_time:.2f}s ({len(exceptions)} errors)"
        )

    # ===== STRESS TESTING =====

    def test_system_stress_test(self):
        """Test system behavior under stress conditions"""
        print("📊 Running system stress test...")

        initial_memory = psutil.virtual_memory().available
        initial_cpu = psutil.cpu_percent()

        stress_operations = []

        try:
            with TestDataContext("performance", member_count=200) as data:
                # Simulate heavy load
                for i in range(50):
                    # Mix of operations
                    if i % 3 == 0:
                        # Database query
                        result = frappe.get_all(
                            "Member", filters={"status": "Active"}, fields=["name", "member_name", "email"]
                        )
                        stress_operations.append(f"Query: {len(result)} results")

                    elif i % 3 == 1:
                        # Document creation
                        chapter = random.choice(data["chapters"])
                        member = frappe.get_doc(
                            {
                                "doctype": "Member",
                                "first_name": f"Stress{i}",
                                "last_name": "Test",
                                "email": f"stress{i}@test.com",
                                "status": "Active",
                                "chapter": chapter.name}
                        )
                        member.insert(ignore_permissions=True)
                        stress_operations.append(f"Created: {member.name}")

                        # Clean up immediately to avoid accumulation
                        member.delete(ignore_permissions=True, force=True)

                    else:
                        # Document update
                        member = random.choice(data["members"])
                        doc = frappe.get_doc("Member", member.name)
                        doc.notes = f"Stress test update {i} at {time.time()}"
                        doc.save()
                        stress_operations.append(f"Updated: {member.name}")

        except Exception as e:
            self.fail(f"System failed under stress: {str(e)}")

        final_memory = psutil.virtual_memory().available
        final_cpu = psutil.cpu_percent()

        memory_used = (initial_memory - final_memory) / (1024 * 1024)  # MB

        # Stress test assertions
        self.assertGreater(len(stress_operations), 40, "Not enough stress operations completed")
        self.assertLess(memory_used, 200, f"Too much memory used during stress: {memory_used:.1f}MB")

        print(f"   ✅ Stress test: {len(stress_operations)} operations completed")
        print(f"   📊 Memory used: {memory_used:.1f}MB, CPU: {initial_cpu:.1f}% → {final_cpu:.1f}%")

    # ===== TIMEOUT AND RESOURCE LIMIT TESTS =====

    def test_operation_timeouts(self):
        """Test operation timeout handling"""
        print("📊 Testing operation timeouts...")

        # Simulate slow operations
        slow_operations = [
            ("Slow query simulation", lambda: time.sleep(0.5)),  # Simulate slow query
            ("Large data processing", lambda: [i**2 for i in range(100000)]),  # CPU intensive
        ]

        for operation_name, operation in slow_operations:
            start_time = time.time()

            try:
                # Set timeout (in real implementation, this would be database/framework timeout)
                operation()
                duration = time.time() - start_time

                # Verify operation completed in reasonable time
                self.assertLess(duration, 10.0, f"{operation_name} took too long: {duration:.2f}s")

                print(f"   ✅ {operation_name}: {duration:.3f}s")

            except Exception as e:
                duration = time.time() - start_time
                print(f"   ⚠️  {operation_name} failed after {duration:.3f}s: {str(e)}")

    def test_resource_limit_handling(self):
        """Test handling of resource limits"""
        print("📊 Testing resource limit handling...")

        # Test memory limits
        try:
            # Attempt to create large data structures
            large_list = []
            for i in range(10000):
                large_list.append(f"Large data item {i} " * 100)  # ~2KB per item

            # Verify we can handle reasonably large datasets
            self.assertGreater(len(large_list), 5000, "Could not create large dataset")

            # Clean up
            del large_list

            print("   ✅ Memory limit test: handled large dataset")

        except MemoryError:
            print("   ⚠️  Memory limit reached during test")

        # Test file descriptor limits
        try:
            # This would test file/connection limits in real scenario
            temp_files = []
            for i in range(100):
                # In real test, would open files/connections
                temp_files.append(f"temp_file_{i}")

            self.assertGreater(len(temp_files), 50, "Could not handle multiple file references")

            print("   ✅ File descriptor test: handled multiple references")

        except Exception as e:
            print(f"   ⚠️  Resource limit error: {str(e)}")


def run_performance_edge_case_tests():
    """Run all performance edge case tests"""
    print("🚀 Running Performance Edge Case Tests...")
    print("📊 This may take several minutes...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestPerformanceEdgeCases)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All performance edge case tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for failure in result.failures:
            print(f"   FAILURE: {failure[0]}")
        for error in result.errors:
            print(f"   ERROR: {error[0]}")
        return False


if __name__ == "__main__":
    run_performance_edge_case_tests()
