#!/usr/bin/env python3
"""
Payment History Scalability Testing Example
===========================================

Example script demonstrating how to use the payment history scalability
testing suite in various scenarios.

This script shows practical examples of:
- Running different test scales
- Generating realistic test data
- Using the configuration system
- Integrating with existing workflows
- Analyzing performance results

Run this script to see the scalability testing suite in action.
"""

import os
import sys
import time

# Add the apps directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import frappe

from verenigingen.tests.config.scalability_test_config import (
    ScalabilityTestConfig,
    get_config_for_environment,
    print_config_summary,
    validate_config_compatibility,
)
from verenigingen.tests.fixtures.payment_history_test_factory import (
    PaymentHistoryTestDataFactory,
    create_payment_history_test_data,
)


def example_1_basic_smoke_test():
    """Example 1: Basic smoke test for development"""

    print("\n🔥 Example 1: Basic Smoke Test")
    print("=" * 50)

    # Initialize Frappe (if not already done)
    if not frappe.local.conf:
        frappe.init("dev.veganisme.net")
        frappe.connect()

    # Get development configuration
    config = get_config_for_environment("development")

    # Show configuration summary
    print_config_summary(config, "smoke")

    # Validate system requirements
    if not validate_config_compatibility(config, "smoke"):
        print("❌ System doesn't meet requirements, skipping example")
        return

    # Create test data factory
    factory = PaymentHistoryTestDataFactory(seed=42)

    try:
        print("\n📊 Generating test data...")
        start_time = time.time()

        # Create 10 members with payment history for quick demo
        members_data = factory.create_bulk_members_with_histories(member_count=10, max_payment_months=3)

        generation_time = time.time() - start_time
        print(f"✅ Generated test data in {generation_time:.2f}s")

        # Show statistics
        total_invoices = sum(len(md["invoices"]) for md in members_data)
        total_payments = sum(len(md["payments"]) for md in members_data)

        print(f"📈 Statistics:")
        print(f"  Members: {len(members_data)}")
        print(f"  Total Invoices: {total_invoices}")
        print(f"  Total Payments: {total_payments}")

        # Test payment history loading for first member
        print(f"\n🧪 Testing payment history loading...")
        test_member = members_data[0]["member"]

        load_start = time.time()
        result = test_member.load_payment_history()
        load_time = time.time() - load_start

        if result:
            print(f"✅ Payment history loaded in {load_time:.3f}s")
            print(f"  Payment history entries: {len(test_member.payment_history)}")
        else:
            print(f"❌ Payment history loading failed")

    finally:
        # Cleanup
        print("\n🧹 Cleaning up test data...")
        factory.cleanup()
        print("✅ Cleanup completed")


def example_2_performance_comparison():
    """Example 2: Performance comparison between different approaches"""

    print("\n⚡ Example 2: Performance Comparison")
    print("=" * 50)

    # Initialize Frappe
    if not frappe.local.conf:
        frappe.init("dev.veganisme.net")
        frappe.connect()

    # Test different member counts to show scaling
    test_counts = [25, 50, 100]
    results = {}

    for count in test_counts:
        print(f"\n📊 Testing with {count} members...")

        factory = PaymentHistoryTestDataFactory(seed=42)

        try:
            # Data generation timing
            gen_start = time.time()
            members_data = factory.create_bulk_members_with_histories(
                member_count=count, max_payment_months=6
            )
            gen_time = time.time() - gen_start

            # Payment history loading timing
            load_start = time.time()
            successful_loads = 0

            for member_data in members_data[:10]:  # Test first 10 members
                member = member_data["member"]
                if member.load_payment_history():
                    successful_loads += 1

            load_time = time.time() - load_start

            # Calculate metrics
            throughput = count / gen_time if gen_time > 0 else 0
            load_throughput = 10 / load_time if load_time > 0 else 0

            results[count] = {
                "generation_time": gen_time,
                "load_time": load_time,
                "generation_throughput": throughput,
                "load_throughput": load_throughput,
                "successful_loads": successful_loads,
            }

            print(f"  Generation: {gen_time:.2f}s ({throughput:.1f} members/s)")
            print(f"  Loading: {load_time:.2f}s ({load_throughput:.1f} members/s)")
            print(f"  Success rate: {successful_loads}/10")

        finally:
            factory.cleanup()

    # Show comparison
    print(f"\n📈 Performance Comparison Summary:")
    print(f"{'Members':<10} {'Gen Time':<10} {'Gen Thru':<12} {'Load Time':<10} {'Load Thru':<12}")
    print("-" * 60)

    for count, metrics in results.items():
        print(
            f"{count:<10} {metrics['generation_time']:<10.2f} "
            f"{metrics['generation_throughput']:<12.1f} "
            f"{metrics['load_time']:<10.2f} "
            f"{metrics['load_throughput']:<12.1f}"
        )


def example_3_edge_case_testing():
    """Example 3: Edge case scenario testing"""

    print("\n🎯 Example 3: Edge Case Testing")
    print("=" * 50)

    # Initialize Frappe
    if not frappe.local.conf:
        frappe.init("dev.veganisme.net")
        frappe.connect()

    factory = PaymentHistoryTestDataFactory(seed=42)

    try:
        print("🔍 Creating edge case scenarios...")

        # Create different payment profiles
        profiles = ["reliable", "typical", "problematic", "sporadic"]
        edge_cases = {}

        for profile in profiles:
            print(f"  Creating {profile} payment profile...")

            member_data = factory.create_member_with_payment_history(
                payment_months=12,
                payment_frequency="Monthly",
                payment_profile=profile,
                include_sepa_mandate=True,
                include_unreconciled=True,
            )

            edge_cases[profile] = member_data

            # Show statistics for this profile
            stats = member_data["statistics"]
            print(f"    Success rate: {stats['success_rate']:.1%}")
            print(f"    Failure rate: {stats['failure_rate']:.1%}")
            print(f"    Collection rate: {stats['collection_rate']:.1%}")

        # Test payment history loading for different profiles
        print(f"\n🧪 Testing payment history loading by profile:")

        for profile, member_data in edge_cases.items():
            member = member_data["member"]

            load_start = time.time()
            result = member.load_payment_history()
            load_time = time.time() - load_start

            status = "✅" if result else "❌"
            print(f"  {profile:<12} {status} {load_time:.3f}s " f"({len(member.payment_history)} entries)")

        # Create and test corrupted data scenario
        print(f"\n⚠️ Testing corrupted data scenarios...")

        # Create member without customer (edge case)
        member = factory.create_test_member()
        original_customer = member.customer
        member.customer = None
        member.save()

        # Test payment history loading with missing customer
        load_start = time.time()
        result = member.load_payment_history()
        load_time = time.time() - load_start

        print(
            f"  Missing customer: {'✅ Handled gracefully' if not result else '❌ Should have failed'} "
            f"({load_time:.3f}s)"
        )

        # Restore customer for cleanup
        member.customer = original_customer
        member.save()

    finally:
        print("\n🧹 Cleaning up edge case test data...")
        factory.cleanup()
        print("✅ Edge case testing completed")


def example_4_configuration_demonstration():
    """Example 4: Configuration system demonstration"""

    print("\n⚙️ Example 4: Configuration System")
    print("=" * 50)

    # Show different environment configurations
    environments = ["development", "production", "ci"]

    for env in environments:
        print(f"\n📋 {env.upper()} Environment Configuration:")
        print("-" * 40)

        config = get_config_for_environment(env)

        # Show available scales for this environment
        for scale in config.TEST_SCALES.keys():
            scale_config = config.get_test_config(scale)
            print(
                f"  {scale:<12} {scale_config['member_count']:<6} members  "
                f"{scale_config['max_execution_time']:<6.0f}s  "
                f"{scale_config['max_memory_usage_mb']:<6.0f}MB"
            )

    # Show system requirements validation
    print(f"\n🖥️ System Requirements Validation:")
    print("-" * 40)

    config = ScalabilityTestConfig()
    scales = ["smoke", "integration", "performance", "stress"]

    for scale in scales:
        validation = config.validate_system_requirements(scale)
        status = "✅" if validation["overall_passed"] else "❌"

        memory = validation["memory_check"]
        print(
            f"  {scale:<12} {status} " f"Memory: {memory['available_gb']:.1f}GB/{memory['required_gb']:.1f}GB"
        )

    # Show optimized configuration for current system
    print(f"\n🎯 Optimized Configuration for Current System:")
    print("-" * 40)

    optimized = config.get_optimized_config_for_environment()
    print(f"  Recommended Scale: {optimized['recommended_scale']}")
    print(f"  System Memory: {optimized['system_capabilities']['memory_gb']:.1f}GB")
    print(f"  System CPU Cores: {optimized['system_capabilities']['cpu_cores']}")

    recommended_config = optimized["scale_config"]
    print(f"  Test Members: {recommended_config['member_count']}")
    print(f"  Max Execution Time: {recommended_config['max_execution_time']}s")


def example_5_integration_with_test_runner():
    """Example 5: Integration with test runner"""

    print("\n🚀 Example 5: Test Runner Integration")
    print("=" * 50)

    # Show how to use the test runner programmatically
    from verenigingen.tests.test_payment_history_scalability import run_payment_history_scalability_tests

    print("🔧 Running smoke test via test runner...")

    # Run smoke test programmatically
    results = run_payment_history_scalability_tests(scale="smoke", verbose=False)  # Reduce output for example

    # Show results
    print(f"✅ Test runner results:")
    print(f"  Success: {results['success']}")
    print(f"  Scale: {results['scale']}")
    print(f"  Return Code: {results['return_code']}")

    # Show command-line usage examples
    print(f"\n📝 Command-line Usage Examples:")
    print(f"  # Basic smoke test")
    print(f"  python run_payment_history_scalability_tests.py --suite smoke")
    print(f"")
    print(f"  # Performance test with HTML report")
    print(f"  python run_payment_history_scalability_tests.py --suite performance --html-report")
    print(f"")
    print(f"  # CI/CD integration")
    print(f"  python run_payment_history_scalability_tests.py --suite integration --ci-mode")
    print(f"")
    print(f"  # Full test suite with monitoring")
    print(f"  python run_payment_history_scalability_tests.py --suite all --monitor-resources")


def main():
    """Run all examples"""

    print("🎬 Payment History Scalability Testing Examples")
    print("=" * 60)
    print("This script demonstrates the payment history scalability testing suite")
    print("with practical examples of different usage scenarios.")

    examples = [
        ("Basic Smoke Test", example_1_basic_smoke_test),
        ("Performance Comparison", example_2_performance_comparison),
        ("Edge Case Testing", example_3_edge_case_testing),
        ("Configuration System", example_4_configuration_demonstration),
        ("Test Runner Integration", example_5_integration_with_test_runner),
    ]

    print(f"\nAvailable examples:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")

    # Run all examples or allow selection
    if len(sys.argv) > 1:
        try:
            example_num = int(sys.argv[1])
            if 1 <= example_num <= len(examples):
                name, example_func = examples[example_num - 1]
                print(f"\n🎯 Running Example {example_num}: {name}")
                example_func()
            else:
                print(f"❌ Invalid example number. Choose 1-{len(examples)}")
        except ValueError:
            print(f"❌ Invalid example number. Choose 1-{len(examples)}")
    else:
        # Run all examples
        for i, (name, example_func) in enumerate(examples, 1):
            print(f"\n🎯 Running Example {i}: {name}")
            try:
                example_func()
            except Exception as e:
                print(f"❌ Example {i} failed: {e}")
                # Continue with other examples

            print(f"✅ Example {i} completed")

    print(f"\n🏁 Examples completed!")
    print(f"\nNext steps:")
    print(f"  1. Run actual scalability tests: python run_payment_history_scalability_tests.py")
    print(f"  2. Review documentation: docs/testing/payment_history_scalability_testing.md")
    print(f"  3. Integrate with CI/CD pipeline using --ci-mode")


if __name__ == "__main__":
    main()
