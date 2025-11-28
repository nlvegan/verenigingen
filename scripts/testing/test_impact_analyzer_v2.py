#!/usr/bin/env python3
"""
Test Impact Analyzer v2 - Tiered test selection for pre-push hooks

Instead of running ALL impacted tests, this uses a tiered approach:
- Tier 1 (Pre-push): Direct unit tests + critical contract tests (~30s)
- Tier 2 (CI): Integration tests for changed modules (~5min)
- Tier 3 (Full): All impacted tests (~15min+)

This makes pre-push practical while ensuring comprehensive CI coverage.
"""

import ast
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


# Test categories with priority
TEST_TIERS = {
    "critical": {
        "patterns": [
            "test_*_contract*.py",  # Contract tests
            "test_operation_result*.py",  # Core infrastructure
        ],
        "always_run": True,  # Always run on any change
    },
    "tier1_unit": {
        "description": "Direct unit tests - fast, targeted",
        "match_strategy": "naming_convention",  # test_X.py for X.py
    },
    "tier2_integration": {
        "description": "Integration tests - import-based matching",
        "match_strategy": "import_analysis",
    },
    "tier3_comprehensive": {
        "description": "Comprehensive tests - broad coverage",
        "match_strategy": "all_impacted",
    },
}

# Files that should trigger minimal tests (docs, config, etc.)
SKIP_TEST_PATTERNS = [
    "*.md",
    "*.rst",
    "*.txt",
    "*.json",  # Config files
    "*.csv",
    "LICENSE",
    ".gitignore",
]

# Critical paths that should always run critical tests
CRITICAL_PATHS = [
    "api/",
    "services/",
    "utils/payment",
    "integrations/mollie",
]


class TieredTestAnalyzer:
    """Tiered test impact analysis for practical pre-push hooks"""

    def __init__(self, repo_path: str = None, verbose: bool = False):
        self.repo_path = Path(repo_path or "/home/frappe/frappe-bench/apps/verenigingen")
        self.test_dir = self.repo_path / "verenigingen" / "tests"
        self.verbose = verbose
        self._import_cache: Dict[str, Set[str]] = {}

    def get_changed_files(self, since: str = "origin/develop") -> List[str]:
        """Get changed Python files via git"""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Fallback to staged + unstaged
                result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                )

            changed = []
            for line in result.stdout.strip().split("\n"):
                if line and line.startswith("verenigingen/") and line.endswith(".py"):
                    changed.append(line)

            return changed

        except subprocess.CalledProcessError:
            return []

    def classify_changes(self, changed_files: List[str]) -> Dict[str, List[str]]:
        """Classify changes by impact level"""
        classification = {
            "critical": [],  # API, services, payments
            "standard": [],  # Regular code
            "tests": [],  # Test files themselves
            "low_impact": [],  # Templates, fixtures, etc.
        }

        for f in changed_files:
            if "/tests/" in f:
                classification["tests"].append(f)
            elif any(crit in f for crit in CRITICAL_PATHS):
                classification["critical"].append(f)
            elif "/templates/" in f or "/fixtures/" in f:
                classification["low_impact"].append(f)
            else:
                classification["standard"].append(f)

        return classification

    def find_tier1_tests(self, changed_files: List[str]) -> Set[str]:
        """Find Tier 1 tests: direct unit tests by EXACT naming convention only"""
        tests = set()

        # Skip very common names that would match too many tests
        SKIP_BASE_NAMES = {
            "member",  # Too broad - matches 100+ tests
            "volunteer",  # Too broad
            "membership",  # Too broad
            "chapter",  # Too broad
            "__init__",
        }

        for changed_file in changed_files:
            if "/tests/" in changed_file:
                continue  # Skip test files

            base_name = Path(changed_file).stem

            # Skip overly broad names
            if base_name in SKIP_BASE_NAMES:
                continue

            # Only look for EXACT test_<basename>.py - no wildcards
            for test_file in self.test_dir.rglob(f"test_{base_name}.py"):
                tests.add(str(test_file))

        return tests

    def find_critical_tests(self) -> Set[str]:
        """Find critical contract tests that should always run"""
        tests = set()

        for pattern in TEST_TIERS["critical"]["patterns"]:
            for test_file in self.test_dir.rglob(pattern):
                tests.add(str(test_file))

        return tests

    def find_service_tests(self, changed_files: List[str]) -> Set[str]:
        """Find service-specific tests for changed service files - CONSERVATIVE"""
        tests = set()

        for changed_file in changed_files:
            if "/services/" in changed_file:
                # Only look for exact test file matches in services test directory
                # e.g., termination_execution_service.py -> test_termination_execution_service.py
                base_name = Path(changed_file).stem

                # Look in services test directory specifically
                services_test_dir = self.test_dir / "services"
                if services_test_dir.exists():
                    for test_file in services_test_dir.glob(f"test_{base_name}.py"):
                        tests.add(str(test_file))

        return tests

    def analyze(self, since: str = "origin/develop", tier: str = "tier1") -> Dict:
        """
        Analyze changes and return tests to run based on tier.

        Tiers:
        - tier1: Quick tests for pre-push (~30s)
        - tier2: Integration tests for CI (~5min)
        - tier3: All impacted tests (~15min+)
        """
        changed_files = self.get_changed_files(since)

        if not changed_files:
            return {
                "tier": tier,
                "changed_files": [],
                "tests": [],
                "command": None,
                "skip_reason": "No Python files changed",
            }

        classification = self.classify_changes(changed_files)
        tests_to_run = set()

        # Always include critical tests if critical paths changed
        if classification["critical"]:
            tests_to_run.update(self.find_critical_tests())

        if tier in ["tier1", "tier2", "tier3"]:
            # Tier 1: Direct unit tests
            tests_to_run.update(self.find_tier1_tests(changed_files))

            # Add service-specific tests
            tests_to_run.update(self.find_service_tests(changed_files))

        if tier in ["tier2", "tier3"]:
            # Tier 2: Would add import-based matching here
            # For now, we rely on CI for comprehensive testing
            pass

        # Filter out non-existent tests
        tests_to_run = {t for t in tests_to_run if Path(t).exists()}

        # Generate command
        command = self._generate_command(tests_to_run)

        return {
            "tier": tier,
            "changed_files": changed_files,
            "classification": classification,
            "tests": sorted(tests_to_run),
            "command": command,
        }

    def _generate_command(self, test_files: Set[str]) -> str:
        """Generate pytest command for the tests"""
        if not test_files:
            return None

        # Convert to module paths
        modules = []
        for test_file in sorted(test_files):
            rel_path = Path(test_file).relative_to(self.repo_path)
            module = str(rel_path).replace("/", ".").replace(".py", "")
            modules.append(module)

        if len(modules) == 1:
            return f"bench --site dev.veganisme.net run-tests --module {modules[0]}"
        elif len(modules) <= 5:
            # For a few modules, chain them
            cmds = [f"bench --site dev.veganisme.net run-tests --module {m}" for m in modules]
            return " && ".join(cmds)
        else:
            # For many modules, suggest running tests directory
            return (
                f"# {len(modules)} tests identified - consider running:\n"
                f"bench --site dev.veganisme.net run-tests --module vereinigingen.tests"
            )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Tiered test impact analysis")
    parser.add_argument("--since", default="origin/develop", help="Git ref to compare against")
    parser.add_argument(
        "--tier",
        choices=["tier1", "tier2", "tier3"],
        default="tier1",
        help="Test tier to run (tier1=quick, tier2=integration, tier3=all)",
    )
    parser.add_argument("--run", action="store_true", help="Run the identified tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    analyzer = TieredTestAnalyzer(verbose=args.verbose)
    result = analyzer.analyze(since=args.since, tier=args.tier)

    # Output
    print(f"🔬 Tiered Test Analysis ({args.tier})")
    print("=" * 60)

    if result.get("skip_reason"):
        print(f"\n✅ {result['skip_reason']}")
        sys.exit(0)

    print(f"\n📝 Changed files: {len(result['changed_files'])}")
    if args.verbose:
        for f in result["changed_files"]:
            print(f"   - {f}")

    if result.get("classification"):
        cls = result["classification"]
        if cls["critical"]:
            print(f"\n⚠️  Critical changes: {len(cls['critical'])}")
            for f in cls["critical"]:
                print(f"   - {f}")

    print(f"\n🎯 Tests to run ({args.tier}): {len(result['tests'])}")
    for t in result["tests"]:
        rel = Path(t).relative_to(analyzer.repo_path)
        print(f"   - {rel}")

    if result["command"]:
        print(f"\n💡 Command:\n   {result['command']}")

    print("\n" + "=" * 60)

    # Run if requested
    if args.run and result["command"] and not result["command"].startswith("#"):
        print("\n🚀 Running tests...")
        exit_code = os.system(result["command"])
        sys.exit(exit_code >> 8)

    # Exit codes: 0=no tests, 1=tests found
    sys.exit(1 if result["tests"] else 0)


if __name__ == "__main__":
    main()
