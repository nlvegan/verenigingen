#!/usr/bin/env python3
"""
File-level Test Runner for Verenigingen

This script discovers and runs individual test files, giving detailed results
and creating an inventory of test coverage.

Usage:
    # List all test files
    python scripts/testing/run_test_files.py --list

    # Run tests from a specific directory
    python scripts/testing/run_test_files.py --dir=verenigingen/tests/services

    # Run specific test file
    python scripts/testing/run_test_files.py --file=verenigingen/tests/test_member_utils.py

    # Run with patterns
    python scripts/testing/run_test_files.py --pattern="*sepa*"

    # Generate test inventory to file
    python scripts/testing/run_test_files.py --inventory --output=test-inventory.txt

    # Run quick smoke tests (one file per category)
    python scripts/testing/run_test_files.py --smoke
"""

import argparse
import fnmatch
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# Root paths for test discovery
TEST_ROOTS = [
    "verenigingen/tests",
    "verenigingen/integrations/mollie/tests",
]

# Files/patterns to skip (these cause fixture issues with --app)
SKIP_PATTERNS = [
    "**/archived/**",
    "**/doctype/**/test_*.py",  # DocType tests often have fixture issues
    "**/__pycache__/**",
]

# Directories known to have working tests
WORKING_DIRS = [
    "verenigingen/tests/services",
    "verenigingen/tests/contracts",
    "verenigingen/tests/integration",
    "verenigingen/tests/security",
    "verenigingen/tests/backend/unit",
    "verenigingen/tests/backend/components",
    "verenigingen/tests/backend/comprehensive",
    "verenigingen/integrations/mollie/tests",
]


def get_site():
    """Get site name from environment or default."""
    import os
    return os.environ.get("SITE", "dev.veganisme.net")


def discover_test_files(root_path: str, pattern: str = "test_*.py") -> list[Path]:
    """Discover all test files in a directory."""
    files = []
    root = Path(root_path)

    if not root.exists():
        return files

    for test_file in root.rglob(pattern):
        # Skip files matching skip patterns
        should_skip = False
        for skip in SKIP_PATTERNS:
            if fnmatch.fnmatch(str(test_file), skip):
                should_skip = True
                break

        if not should_skip:
            files.append(test_file)

    return sorted(files)


def file_to_module(file_path: Path) -> str:
    """Convert file path to Python module path."""
    # Remove .py extension and convert path separators to dots
    parts = file_path.with_suffix("").parts

    # Find 'verenigingen' in path and start from there
    try:
        idx = parts.index("verenigingen")
        return ".".join(parts[idx:])
    except ValueError:
        return ".".join(parts)


def run_test_file(file_path: Path, site: str, verbose: bool = False) -> tuple[bool, str, int]:
    """Run a single test file and return (success, output, test_count)."""
    module = file_to_module(file_path)

    cmd = [
        "bench",
        "--site", site,
        "run-tests",
        "--module", module,
    ]

    if verbose:
        print(f"    Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout per file
            cwd="/home/frappe/frappe-bench"
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        # Extract test count
        test_count = 0
        for line in output.split("\n"):
            if "Ran " in line and " test" in line:
                try:
                    test_count = int(line.split("Ran ")[1].split(" ")[0])
                except (ValueError, IndexError):
                    pass
                break

        return success, output, test_count

    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT: File {file_path} exceeded 2 minute limit", 0
    except Exception as e:
        return False, f"ERROR: {str(e)}", 0


def list_test_files(pattern: str = None):
    """List all discovered test files."""
    print("\nDiscovered Test Files")
    print("=" * 60)

    total = 0
    for root in TEST_ROOTS:
        files = discover_test_files(root)
        if pattern:
            files = [f for f in files if fnmatch.fnmatch(f.name, pattern)]

        if files:
            print(f"\n{root}:")
            for f in files:
                rel_path = f.relative_to(Path.cwd()) if f.is_absolute() else f
                print(f"  {rel_path}")
                total += 1

    print(f"\n\nTotal: {total} test files")


def generate_inventory(output_file: str = None):
    """Generate a full inventory of test files with module paths."""
    lines = []
    lines.append("Test File Inventory")
    lines.append("=" * 60)
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append("")

    total = 0
    for root in TEST_ROOTS:
        files = discover_test_files(root)
        if files:
            lines.append(f"\n{root}:")
            lines.append("-" * 40)
            for f in files:
                module = file_to_module(f)
                lines.append(f"  {f.name}")
                lines.append(f"    Module: {module}")
                total += 1

    lines.append("")
    lines.append(f"Total: {total} test files")

    content = "\n".join(lines)

    if output_file:
        with open(output_file, "w") as f:
            f.write(content)
        print(f"Inventory written to: {output_file}")
    else:
        print(content)


def run_directory_tests(directory: str, site: str, verbose: bool = False,
                       pattern: str = None, limit: int = None):
    """Run all tests in a directory."""
    dir_path = Path(directory)
    files = discover_test_files(str(dir_path))

    if pattern:
        files = [f for f in files if fnmatch.fnmatch(f.name, pattern)]

    if limit:
        files = files[:limit]

    if not files:
        print(f"No test files found in {directory}")
        return {"passed": 0, "failed": 0, "total_tests": 0}

    results = {"passed": 0, "failed": 0, "total_tests": 0, "files": {}}

    print(f"\nRunning {len(files)} test files from {directory}")
    print("-" * 60)

    for f in files:
        print(f"  {f.name}...", end=" ", flush=True)
        success, output, test_count = run_test_file(f, site, verbose)

        if success:
            print(f"PASS ({test_count} tests)")
            results["passed"] += 1
        else:
            print(f"FAIL")
            results["failed"] += 1
            if verbose:
                print(f"    {output[:200]}...")

        results["total_tests"] += test_count
        results["files"][str(f)] = {"success": success, "tests": test_count}

    return results


def run_smoke_tests(site: str, verbose: bool = False):
    """Run one test from each major category for quick validation."""
    smoke_tests = [
        "verenigingen/tests/services/test_operation_result_migration.py",
        "verenigingen/tests/services/test_termination_operations.py",
        "verenigingen/integrations/mollie/tests/test_core_integration.py",
    ]

    print("\nSmoke Tests (quick validation)")
    print("=" * 60)

    results = {"passed": 0, "failed": 0}

    for test_path in smoke_tests:
        f = Path(test_path)
        if not f.exists():
            print(f"  {f.name}: SKIP (not found)")
            continue

        print(f"  {f.name}...", end=" ", flush=True)
        success, output, test_count = run_test_file(f, site, verbose)

        if success:
            print(f"PASS ({test_count} tests)")
            results["passed"] += 1
        else:
            print("FAIL")
            results["failed"] += 1
            if verbose:
                print(f"    {output[:200]}...")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="File-level test runner for Verenigingen",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument("--list", "-l", action="store_true", help="List all test files")
    parser.add_argument("--inventory", "-i", action="store_true", help="Generate test inventory")
    parser.add_argument("--dir", "-d", help="Run tests from specific directory")
    parser.add_argument("--file", "-f", help="Run a specific test file")
    parser.add_argument("--pattern", "-p", help="Filter files by pattern (e.g., '*sepa*')")
    parser.add_argument("--smoke", action="store_true", help="Run quick smoke tests")
    parser.add_argument("--site", "-s", default=None, help="Site name")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--output", "-o", help="Output file for results")
    parser.add_argument("--limit", type=int, help="Limit number of files to run")

    args = parser.parse_args()

    site = args.site or get_site()

    if args.list:
        list_test_files(args.pattern)
        return 0

    if args.inventory:
        generate_inventory(args.output)
        return 0

    start_time = datetime.now()

    if args.smoke:
        results = run_smoke_tests(site, args.verbose)
    elif args.file:
        f = Path(args.file)
        print(f"\nRunning: {f}")
        success, output, test_count = run_test_file(f, site, args.verbose)
        if success:
            print(f"PASS ({test_count} tests)")
        else:
            print(f"FAIL\n{output}")
        results = {"passed": 1 if success else 0, "failed": 0 if success else 1}
    elif args.dir:
        results = run_directory_tests(args.dir, site, args.verbose, args.pattern, args.limit)
    else:
        # Default: run all tests
        all_results = {"passed": 0, "failed": 0, "total_tests": 0}
        for root in TEST_ROOTS:
            dir_results = run_directory_tests(root, site, args.verbose, args.pattern, args.limit)
            all_results["passed"] += dir_results["passed"]
            all_results["failed"] += dir_results["failed"]
            all_results["total_tests"] += dir_results["total_tests"]
        results = all_results

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Passed: {results.get('passed', 0)}")
    print(f"Failed: {results.get('failed', 0)}")
    if 'total_tests' in results:
        print(f"Total Tests: {results['total_tests']}")
    print(f"Duration: {duration:.1f}s")

    return 0 if results.get('failed', 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
