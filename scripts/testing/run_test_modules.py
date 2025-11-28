#!/usr/bin/env python3
"""
Comprehensive Test Runner for Verenigingen

This script runs tests by module to avoid DocType fixture ordering issues
that occur when using `bench run-tests --app`.

Usage:
    # Run all module tests (skip problematic doctype tests)
    python scripts/testing/run_test_modules.py --all

    # Run specific categories
    python scripts/testing/run_test_modules.py --category=services
    python scripts/testing/run_test_modules.py --category=contracts
    python scripts/testing/run_test_modules.py --category=security

    # Run a specific module
    python scripts/testing/run_test_modules.py --module=verenigingen.tests.services

    # List available categories
    python scripts/testing/run_test_modules.py --list

    # Dry run (show what would be tested)
    python scripts/testing/run_test_modules.py --all --dry-run
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Test module categories - these are the tests that can run reliably
# without doctype fixture issues
TEST_CATEGORIES = {
    "contracts": {
        "description": "Contract tests (critical for CI)",
        "modules": [
            "verenigingen.tests.contracts",
        ],
    },
    "services": {
        "description": "Service layer tests",
        "modules": [
            "verenigingen.tests.services",
            "verenigingen.tests.services.test_operation_result_migration",
            "verenigingen.tests.services.test_termination_operations",
        ],
    },
    "integration": {
        "description": "Integration tests",
        "modules": [
            "verenigingen.tests.integration",
        ],
    },
    "security": {
        "description": "Security tests",
        "modules": [
            "verenigingen.tests.security",
        ],
    },
    "backend_unit": {
        "description": "Backend unit tests",
        "modules": [
            "verenigingen.tests.backend.unit",
        ],
    },
    "backend_components": {
        "description": "Backend component tests",
        "modules": [
            "verenigingen.tests.backend.components",
        ],
    },
    "backend_comprehensive": {
        "description": "Backend comprehensive tests",
        "modules": [
            "verenigingen.tests.backend.comprehensive",
        ],
    },
    "mollie": {
        "description": "Mollie payment integration tests",
        "modules": [
            "verenigingen.integrations.mollie.tests.test_core_integration",
        ],
    },
    "performance": {
        "description": "Performance tests",
        "modules": [
            "verenigingen.tests.performance",
        ],
    },
    "resilience": {
        "description": "Resilience tests",
        "modules": [
            "verenigingen.tests.resilience",
        ],
    },
    "workflows": {
        "description": "Workflow tests",
        "modules": [
            "verenigingen.tests.workflows",
        ],
    },
    "financial": {
        "description": "Financial tests",
        "modules": [
            "verenigingen.tests.financial",
        ],
    },
    "e_boekhouden": {
        "description": "E-Boekhouden integration tests",
        "modules": [
            "vereinigingen.tests.e_boekhouden",
        ],
    },
}

# All modules in recommended order
ALL_MODULE_ORDER = [
    "contracts",
    "services",
    "backend_unit",
    "backend_components",
    "security",
    "integration",
    "mollie",
]

# Essential/critical tests for quick validation
ESSENTIAL_CATEGORIES = ["contracts", "services"]


def get_site():
    """Get site name from environment or default."""
    import os
    return os.environ.get("SITE", "dev.veganisme.net")


def run_module_tests(module: str, site: str, verbose: bool = False) -> tuple[bool, str]:
    """Run tests for a specific module and return (success, output)."""
    cmd = [
        "bench",
        "--site", site,
        "run-tests",
        "--module", module,
    ]

    if verbose:
        print(f"  Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout per module
            cwd="/home/frappe/frappe-bench"
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        return success, output

    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT: Module {module} exceeded 5 minute limit"
    except Exception as e:
        return False, f"ERROR: {str(e)}"


def run_category(category: str, site: str, verbose: bool = False, dry_run: bool = False) -> dict:
    """Run all tests in a category."""
    if category not in TEST_CATEGORIES:
        print(f"Unknown category: {category}")
        return {"success": False, "modules": {}}

    cat_info = TEST_CATEGORIES[category]
    results = {"success": True, "modules": {}}

    print(f"\n{'='*60}")
    print(f"Category: {category} - {cat_info['description']}")
    print(f"{'='*60}")

    for module in cat_info["modules"]:
        if dry_run:
            print(f"  [DRY RUN] Would test: {module}")
            results["modules"][module] = {"success": True, "dry_run": True}
        else:
            print(f"  Testing: {module}...", end=" ", flush=True)
            success, output = run_module_tests(module, site, verbose)

            if success:
                # Count tests from output
                test_count = "?"
                for line in output.split("\n"):
                    if "Ran " in line and " test" in line:
                        test_count = line.split("Ran ")[1].split(" ")[0]
                        break
                print(f"PASS ({test_count} tests)")
            else:
                print("FAIL")
                if verbose:
                    print(f"    Output:\n{output[:500]}...")

            results["modules"][module] = {"success": success, "output": output}

            if not success:
                results["success"] = False

    return results


def list_categories():
    """List all available test categories."""
    print("\nAvailable Test Categories:")
    print("-" * 60)

    for name, info in TEST_CATEGORIES.items():
        print(f"\n  {name}:")
        print(f"    Description: {info['description']}")
        print(f"    Modules: {len(info['modules'])}")
        for mod in info['modules']:
            print(f"      - {mod}")


def main():
    parser = argparse.ArgumentParser(
        description="Run Verenigingen tests by module",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument("--all", action="store_true", help="Run all test categories")
    parser.add_argument("--essential", action="store_true", help="Run essential/critical tests only")
    parser.add_argument("--category", "-c", help="Run tests from a specific category")
    parser.add_argument("--module", "-m", help="Run a specific module directly")
    parser.add_argument("--list", "-l", action="store_true", help="List available categories")
    parser.add_argument("--site", "-s", default=None, help="Site name (default: dev.veganisme.net)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be tested without running")
    parser.add_argument("--output", "-o", help="Write results to file")

    args = parser.parse_args()

    if args.list:
        list_categories()
        return 0

    site = args.site or get_site()
    all_results = {}
    start_time = datetime.now()

    print(f"\nVerenigingen Test Runner")
    print(f"Site: {site}")
    print(f"Started: {start_time.isoformat()}")

    if args.module:
        # Run a specific module
        print(f"\nRunning module: {args.module}")
        if args.dry_run:
            print(f"  [DRY RUN] Would test: {args.module}")
        else:
            success, output = run_module_tests(args.module, site, args.verbose)
            if success:
                print("  PASS")
            else:
                print(f"  FAIL")
                if args.verbose:
                    print(output)
            all_results[args.module] = {"success": success, "output": output}

    elif args.category:
        # Run a specific category
        results = run_category(args.category, site, args.verbose, args.dry_run)
        all_results[args.category] = results

    elif args.essential:
        # Run essential tests
        print("\nRunning ESSENTIAL tests...")
        for cat in ESSENTIAL_CATEGORIES:
            results = run_category(cat, site, args.verbose, args.dry_run)
            all_results[cat] = results

    elif args.all:
        # Run all categories in order
        print("\nRunning ALL test categories...")
        for cat in ALL_MODULE_ORDER:
            if cat in TEST_CATEGORIES:
                results = run_category(cat, site, args.verbose, args.dry_run)
                all_results[cat] = results

    else:
        parser.print_help()
        return 1

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    total_pass = 0
    total_fail = 0

    for name, result in all_results.items():
        if isinstance(result, dict) and "modules" in result:
            for mod, mod_result in result["modules"].items():
                if mod_result.get("success"):
                    total_pass += 1
                else:
                    total_fail += 1
        elif isinstance(result, dict):
            if result.get("success"):
                total_pass += 1
            else:
                total_fail += 1

    print(f"Passed: {total_pass}")
    print(f"Failed: {total_fail}")
    print(f"Duration: {duration:.1f}s")
    print(f"Finished: {end_time.isoformat()}")

    # Write results to file if requested
    if args.output:
        with open(args.output, "w") as f:
            import json
            json.dump({
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "passed": total_pass,
                "failed": total_fail,
                "results": {k: {"success": v.get("success")} for k, v in all_results.items()},
            }, f, indent=2)
        print(f"\nResults written to: {args.output}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
