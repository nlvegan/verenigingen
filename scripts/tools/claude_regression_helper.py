#!/usr/bin/env python3
"""
Claude Code Regression Testing Helper
Provides commands for Claude to automatically run regression tests
"""

import json
import os
import subprocess
import time
from datetime import datetime

import psutil


def get_system_metrics():
    """Get current system performance metrics"""
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_available_gb": psutil.virtual_memory().available / (1024**3),
        "disk_usage_percent": psutil.disk_usage(".").percent,
        "timestamp": datetime.now().isoformat(),
    }


def time_command(cmd, description=""):
    """Time a command execution and collect metrics"""
    start_time = time.time()
    start_metrics = get_system_metrics()

    result = subprocess.run(cmd.split(), capture_output=True, text=True)

    end_time = time.time()
    end_metrics = get_system_metrics()
    execution_time = end_time - start_time

    return {
        "command": cmd,
        "description": description,
        "success": result.returncode == 0,
        "execution_time": execution_time,
        "output": result.stdout + result.stderr,
        "start_metrics": start_metrics,
        "end_metrics": end_metrics,
        "peak_cpu": max(start_metrics["cpu_percent"], end_metrics["cpu_percent"]),
        "memory_used_gb": start_metrics["memory_available_gb"] - end_metrics["memory_available_gb"],
    }


def save_performance_baseline(results, baseline_file="performance_baseline.json"):
    """Save performance baseline for comparison"""
    baseline_data = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
        "system_info": {
            "cpu_count": psutil.cpu_count(),
            "total_memory_gb": psutil.virtual_memory().total / (1024**3),
            "python_version": subprocess.run(
                ["python3", "--version"], capture_output=True, text=True
            ).stdout.strip(),
        },
    }

    with open(baseline_file, "w") as f:
        json.dump(baseline_data, f, indent=2)

    print(f"📊 Performance baseline saved to {baseline_file}")


def run_performance_baseline():
    """Run performance baseline before making changes"""
    print("📊 Running performance baseline tests...")

    performance_commands = [
        ("python3 verenigingen/tests/test_runner.py smoke", "Smoke tests"),
        ("python3 run_volunteer_portal_tests.py --suite core", "Core functionality tests"),
        ("python3 verenigingen/tests/test_security_comprehensive.py", "Security tests"),
    ]

    results = {}
    total_time = 0

    for cmd, description in performance_commands:
        print(f"⏱️  Timing: {description}")
        result = time_command(cmd, description)
        results[cmd] = result

        status = "✅" if result["success"] else "❌"
        print(f"{status} {description}: {result['execution_time']:.2f}s (CPU: {result['peak_cpu']:.1f}%)")
        total_time += result["execution_time"]

    print(f"\n📊 Total baseline time: {total_time:.2f}s")
    save_performance_baseline(results)

    return results


def run_pre_change_tests():
    """Run baseline tests before making changes"""
    print("🔵 Running pre-change regression baseline...")

    # Run performance baseline first
    performance_results = run_performance_baseline()

    # Run standard tests
    commands = [
        "python3 verenigingen/tests/test_runner.py smoke",
        "python3 run_volunteer_portal_tests.py --suite core",
    ]

    results = {}
    for cmd in commands:
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        results[cmd] = {"success": result.returncode == 0, "output": result.stdout + result.stderr}
        status = "✅" if result.returncode == 0 else "❌"
        print(f"{status} {cmd}")

    # Combine results
    results["performance_baseline"] = performance_results
    return results


def compare_performance(baseline_file="performance_baseline.json"):
    """Compare current performance with baseline"""
    if not os.path.exists(baseline_file):
        print("⚠️  No performance baseline found. Run pre-change tests first.")
        return None

    print("📊 Comparing performance with baseline...")

    # Load baseline
    with open(baseline_file, "r") as f:
        baseline_data = json.load(f)

    # Run current performance tests
    current_results = run_performance_baseline()

    # Compare results
    comparisons = {}
    for cmd in current_results:
        if cmd in baseline_data["results"]:
            baseline_time = baseline_data["results"][cmd]["execution_time"]
            current_time = current_results[cmd]["execution_time"]

            time_diff = current_time - baseline_time
            time_ratio = (current_time / baseline_time) if baseline_time > 0 else float("inf")

            comparisons[cmd] = {
                "baseline_time": baseline_time,
                "current_time": current_time,
                "time_difference": time_diff,
                "time_ratio": time_ratio,
                "performance_change": "improved"
                if time_diff < -0.5
                else "degraded"
                if time_diff > 0.5
                else "stable",
            }

            # Print comparison
            change_icon = "🚀" if time_diff < -0.5 else "🐌" if time_diff > 0.5 else "📊"
            print(
                f"{change_icon} {current_results[cmd]['description']}: {current_time:.2f}s (was {baseline_time:.2f}s, {time_diff:+.2f}s)"
            )

    return comparisons


def run_post_change_tests():
    """Run comprehensive tests after making changes"""
    print("🟢 Running post-change regression tests...")

    # Compare performance with baseline
    performance_comparison = compare_performance()

    # Run the full regression suite
    result = subprocess.run(["python3", "regression_test_runner.py"], capture_output=True, text=True)

    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)

    # Check for performance regressions
    if performance_comparison:
        performance_issues = [
            cmd
            for cmd, comparison in performance_comparison.items()
            if comparison["performance_change"] == "degraded"
        ]

        if performance_issues:
            print(f"\n⚠️  Performance regressions detected in {len(performance_issues)} test(s)")
            for cmd in performance_issues:
                comp = performance_comparison[cmd]
                print(
                    f"   - {comp['current_time']:.2f}s vs {comp['baseline_time']:.2f}s ({comp['time_ratio']:.2f}x slower)"
                )

    return result.returncode == 0


def run_targeted_tests(component):
    """Run tests for specific component (member, volunteer, team, etc.)"""
    component_tests = {
        "member": [
            "bench run-tests --app verenigingen --module verenigingen.tests.test_member",
            "python3 verenigingen/tests/test_runner.py smoke",
        ],
        "volunteer": [
            "bench run-tests --app verenigingen --module verenigingen.tests.test_volunteer_portal_working",
            "python3 run_volunteer_portal_tests.py --suite core",
        ],
        "team": [
            "bench run-tests --app verenigingen --module verenigingen.tests.test_team_assignment_history",
            "python3 verenigingen/tests/test_runner.py diagnostic",
        ],
        "termination": [
            "bench run-tests --app verenigingen --module verenigingen.tests.test_termination_system",
            "python3 verenigingen/tests/test_runner.py all",
        ],
        "reports": ["python3 verenigingen/tests/test_runner.py smoke"],
    }

    tests = component_tests.get(component, ["python3 verenigingen/tests/test_runner.py smoke"])

    print(f"🎯 Running targeted tests for: {component}")
    results = {}

    for cmd in tests:
        print(f"Running: {cmd}")
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        results[cmd] = result.returncode == 0
        status = "✅" if result.returncode == 0 else "❌"
        print(f"{status} {cmd}")

        if result.returncode != 0:
            print(f"Error output: {result.stderr}")

    return all(results.values())


def check_test_coverage():
    """Check current test coverage"""
    print("📊 Checking test coverage...")

    result = subprocess.run(
        ["python3", "run_volunteer_portal_tests.py", "--coverage"], capture_output=True, text=True
    )

    print(result.stdout)
    return result.returncode == 0


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python claude_regression_helper.py pre-change")
        print("  python claude_regression_helper.py post-change")
        print("  python claude_regression_helper.py targeted <component>")
        print("  python claude_regression_helper.py coverage")
        return 1

    command = sys.argv[1]

    if command == "pre-change":
        run_pre_change_tests()
    elif command == "post-change":
        success = run_post_change_tests()
        return 0 if success else 1
    elif command == "targeted" and len(sys.argv) > 2:
        component = sys.argv[2]
        success = run_targeted_tests(component)
        return 0 if success else 1
    elif command == "coverage":
        check_test_coverage()
    else:
        print("Unknown command")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
