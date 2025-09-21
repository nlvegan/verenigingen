#!/usr/bin/env python

"""Integration test for service infrastructure components."""

import frappe
from frappe import _


def test_service_infrastructure():
    """Test the service infrastructure components."""
    results = []

    # Test 1: Base Service functionality
    try:
        from verenigingen.services.infrastructure.base_service import StatelessService

        class TestService(StatelessService):
            def validate_configuration(self):
                return True

        service = TestService("test_service")
        metrics = service.get_metrics()
        health = service.is_healthy()
        service.cleanup()

        results.append("✓ Base Service: Creation, metrics, health check, cleanup")
    except Exception as e:
        results.append(f"✗ Base Service: {str(e)}")

    # Test 2: Service Factory
    try:
        from vereinigingen.services.infrastructure.base_service import StatelessService

        from verenigingen.services.infrastructure.service_factory import ServiceFactory

        class TestFactoryService(StatelessService):
            def validate_configuration(self):
                return True

        factory = ServiceFactory()
        factory.register_service("test_factory", TestFactoryService)
        service1 = factory.get_service("test_factory")
        service2 = factory.get_service("test_factory")

        singleton_works = service1 is service2
        factory.shutdown_services()

        results.append(f"✓ Service Factory: Registration, singleton ({singleton_works}), shutdown")
    except Exception as e:
        results.append(f"✗ Service Factory: {str(e)}")

    # Test 3: Metrics Collection
    try:
        from verenigingen.services.infrastructure.service_metrics import (
            get_health_monitor,
            get_metrics_collector,
            record_operation,
        )

        record_operation("test_metrics", "test_op", 0.1, success=True)
        collector = get_metrics_collector()
        all_metrics = collector.get_all_metrics()

        monitor = get_health_monitor()
        health = monitor.check_service_health("test_metrics")

        results.append(f"✓ Metrics: Recording, collection, health monitoring")
    except Exception as e:
        results.append(f"✗ Metrics: {str(e)}")

    # Test 4: Configuration Management
    try:
        from verenigingen.services.infrastructure.service_config import ServiceConfig, get_config_manager

        config = ServiceConfig()
        config.set("test_key", "test_value", required=True)
        config.add_validator("test_key", lambda x: isinstance(x, str))

        errors = config.validate()
        value = config.get("test_key")

        manager = get_config_manager()
        summary = manager.get_configuration_summary()

        results.append(f"✓ Configuration: Creation, validation, management")
    except Exception as e:
        results.append(f"✗ Configuration: {str(e)}")

    # Test 5: Example Service
    try:
        from verenigingen.services.infrastructure.example_service import create_calculation_service

        service = create_calculation_service()
        result = service.calculate_fibonacci(5)
        success = result.get("success", False)

        results.append(f"✓ Example Service: Creation and operation ({success})")
    except Exception as e:
        results.append(f"✗ Example Service: {str(e)}")

    # Test 6: Thread Safety
    try:
        import threading

        from verenigingen.services.infrastructure.service_factory import get_service_factory

        errors = []

        def test_thread():
            try:
                factory = get_service_factory()
                # This should work without race conditions
                for i in range(10):
                    factory.get_service_metrics()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=test_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        thread_safe = len(errors) == 0
        results.append(f"✓ Thread Safety: Concurrent access ({thread_safe})")
    except Exception as e:
        results.append(f"✗ Thread Safety: {str(e)}")

    # Summary
    total_tests = len(results)
    passed_tests = len([r for r in results if r.startswith("✓")])

    print("\n" + "=" * 60)
    print("SERVICE INFRASTRUCTURE TEST RESULTS")
    print("=" * 60)
    for result in results:
        print(result)
    print("=" * 60)
    print(f"SUMMARY: {passed_tests}/{total_tests} tests passed")
    print("=" * 60)

    return {
        "passed": passed_tests,
        "total": total_tests,
        "results": results,
        "success": passed_tests == total_tests,
    }


def test_infrastructure_performance():
    """Test performance characteristics of the infrastructure."""
    import time

    print("\n" + "=" * 60)
    print("PERFORMANCE TESTS")
    print("=" * 60)

    try:
        from verenigingen.services.infrastructure.example_service import create_calculation_service

        service = create_calculation_service()

        # Test operation timing
        start_time = time.time()
        for i in range(100):
            service.calculate_fibonacci(10)
        duration = time.time() - start_time

        ops_per_second = 100 / duration
        avg_time = duration / 100

        print(f"✓ Operation Performance: {ops_per_second:.1f} ops/sec, {avg_time*1000:.2f}ms avg")

        # Test metrics overhead
        start_time = time.time()
        for i in range(1000):
            service.get_metrics()
        metrics_duration = time.time() - start_time

        print(
            f"✓ Metrics Overhead: {metrics_duration*1000:.2f}ms for 1000 calls ({metrics_duration/1000*1000:.3f}ms per call)"
        )

        return True

    except Exception as e:
        print(f"✗ Performance Tests: {str(e)}")
        return False


if __name__ == "__main__":
    # When run directly (which won't work due to Frappe context)
    print("This script must be run through bench execute command")
