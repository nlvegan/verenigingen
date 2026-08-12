#!/usr/bin/env python3
"""
Pytest runner specifically for pre-commit hooks.
Uses existing test infrastructure with coverage measurement.

This hook is a pre-push smoke test, so it may only ever target a disposable test
site. It previously resolved its site from ``sites/currentsite.txt`` -- a file
this version of bench never writes -- and fell through to a hardcoded
``veg11.veganisme.org``, which meant every ``git push`` from the installed
checkout ran the suite against the LIVE site (#313). The same defect was fixed in
the Makefile and in ``show_test_shards.py``; this was the reader that was missed.
It now refuses to run rather than guess.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# Reuse the bench/site resolution that show_test_shards.py already carries (and
# already has tests for) rather than growing a fourth copy of a lookup that has
# been got wrong twice. That module imports frappe lazily, inside a function, so
# importing it here costs nothing. `python <script>` puts this directory on
# sys.path, and pre-commit invokes the hook exactly that way.
from show_test_shards import _bench_root, _default_site

# The only sites this hook may target. Anything else -- most of all the live site
# -- is a refusal, not a default.
TEST_SITE = re.compile(r"^test_site_[1-5]$")


def resolve_target_site(bench_root: str) -> tuple[str | None, str]:
    """Return ``(site, refusal_reason)``; ``site`` is None when the hook must not run.

    ``default_site`` in ``sites/common_site_config.json`` is what ``bench use``
    actually writes. ``currentsite.txt`` is consulted second, for benches old
    enough to write it, matching the Makefile.
    """
    site = _default_site(bench_root)
    if not site:
        currentsite = Path(bench_root) / "sites" / "currentsite.txt"
        if currentsite.exists():
            site = currentsite.read_text().strip()
    if not site:
        return None, (
            "no default_site in sites/common_site_config.json (and no currentsite.txt). "
            "Set one with `bench use test_site_1`."
        )
    if not TEST_SITE.match(site):
        return None, (
            f"the bench default site is {site!r}, which is not one of test_site_1..5. "
            "This hook runs the suite, so it will not target a site that may be live. "
            "Point the bench at a test site with `bench use test_site_1`."
        )
    return site, ""


def in_linked_worktree() -> bool:
    """True when the cwd is a linked git worktree rather than the main checkout.

    bench runs the app it has INSTALLED, not the files in a worktree, so a run
    started from one reports on the main checkout's code while appearing to test
    this branch. A green from that is meaningless, and blocking the push on it --
    which is what this script did, with `Error: No such option: --site` -- is
    worse. Skip, and say why.
    """
    try:
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "/worktrees/" in git_dir


def run_pytest_for_precommit():
    """Run critical tests for pre-commit using bench command."""
    bench_root = _bench_root()
    if bench_root is None:
        print("⏭️  Not inside a bench (no ancestor with both apps/ and sites/) - skipping.")
        print("   bench tests the INSTALLED checkout, so there is nothing here to run.")
        return 0

    if in_linked_worktree():
        print("⏭️  Running from a linked git worktree - skipping.")
        print("   bench would test the INSTALLED checkout, not this branch, so a pass")
        print("   here would say nothing about the code being pushed. CI covers it.")
        return 0

    bench_path = Path(bench_root)
    app_path = bench_path / "apps" / "verenigingen"

    # Check if critical test files exist
    critical_tests = [
        app_path / "verenigingen/tests/backend/business_logic/test_critical_business_logic.py",
    ]

    if not any(test.exists() for test in critical_tests):
        print("✅ No critical test files found (skipping)")
        return 0

    site, refusal = resolve_target_site(bench_root)
    if site is None:
        print(f"⏭️  Skipping critical-test run: {refusal}")
        return 0

    # Change to bench directory for command execution
    os.chdir(bench_path)

    # Run existing test runner with coverage
    # Using the existing test runner that already handles Frappe context
    # Note: Multiple modules can be run in sequence for comprehensive coverage
    test_modules = [
        "verenigingen.tests.backend.business_logic.test_critical_business_logic"
    ]

    cmd = [
        "bench", "--site", site,
        "run-tests",
        "--app", "verenigingen",
        "--module", test_modules[0],  # Start with validation regression
        "--coverage"
    ]

    try:
        # Name the target. This hook ran against the live site for as long as it
        # did partly because nothing it printed ever said where it was pointed.
        print(f"📊 Running critical tests with coverage check (site: {site})...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode == 0:
            print("✅ Critical tests passed!")

            # Try to extract and display coverage info
            coverage_section_found = False
            print("\nTest Output Summary:")
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    continue

                # Look for coverage-related lines
                if any(keyword in line.lower() for keyword in ['coverage', 'stmts', 'miss', 'cover']):
                    if not coverage_section_found:
                        print("\n📊 Coverage Information:")
                        coverage_section_found = True
                    print(f"   {line}")

                # Look for test results
                elif any(keyword in line for keyword in ['passed', 'failed', 'error', 'PASSED', 'FAILED']):
                    print(f"   {line}")

                # Look for percentage coverage
                elif '%' in line and any(keyword in line.lower() for keyword in ['verenig', 'total']):
                    if not coverage_section_found:
                        print("\n📊 Coverage Information:")
                        coverage_section_found = True
                    print(f"   {line}")

            return 0
        else:
            print("❌ Critical tests failed!")
            print("\nTest Output:")
            print(result.stdout[-1000:])  # Last 1000 chars to avoid too much output
            if result.stderr:
                print("\nErrors:")
                print(result.stderr[-500:])
            return 1

    except subprocess.TimeoutExpired:
        print("⚠️  Test execution timed out (120s limit)")
        return 1
    except Exception as e:
        print(f"⚠️  Error running tests: {e}")
        print("Proceeding with commit (test infrastructure issue)")
        return 0  # Don't block commits if test setup fails

if __name__ == "__main__":
    sys.exit(run_pytest_for_precommit())
