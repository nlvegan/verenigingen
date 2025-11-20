#!/usr/bin/env python3
"""
Test Impact Analyzer - Automatically detect and run tests affected by code changes

This tool analyzes git changes and Python imports to intelligently determine which
tests need to run based on what code has changed. Combines AST analysis with git
diff detection for accurate, fast test selection.

Usage:
    # Analyze changes since last commit
    python test_impact_analyzer.py

    # Analyze changes in a specific branch
    python test_impact_analyzer.py --branch develop

    # Run impacted tests automatically
    python test_impact_analyzer.py --run

    # Show detailed analysis
    python test_impact_analyzer.py --verbose
"""

import ast
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple


class TestImpactAnalyzer:
    """Analyze code changes and determine which tests are impacted"""

    def __init__(self, repo_path: str = None, verbose: bool = False):
        self.repo_path = Path(repo_path or "/home/frappe/frappe-bench/apps/verenigingen")
        self.test_dir = self.repo_path / "verenigingen" / "tests"
        self.source_dir = self.repo_path / "verenigingen"
        self.verbose = verbose

        # Cache for import analysis
        self._import_cache: Dict[str, Set[str]] = {}
        self._dependency_graph: Dict[str, Set[str]] = defaultdict(set)

    def get_changed_files(self, since: str = "HEAD~1") -> List[str]:
        """Get list of changed Python files via git"""
        try:
            # Get changed files (handle shallow clones)
            result = subprocess.run(
                ["git", "diff", "--name-only", since],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )

            # If git diff fails (shallow clone, not enough history), check unstaged changes
            if result.returncode != 0:
                if self.verbose:
                    print("⚠️  Could not compare against", since, "- checking unstaged changes instead")
                result = subprocess.run(
                    ["git", "diff", "--name-only"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    check=True
                )

            # Filter for Python files in verenigingen directory
            changed_files = []
            for line in result.stdout.strip().split('\n'):
                if line.endswith('.py') and line.startswith('verenigingen/'):
                    changed_files.append(line)

            # Also check staged changes
            staged_result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )

            for line in staged_result.stdout.strip().split('\n'):
                if line.endswith('.py') and line.startswith('verenigingen/'):
                    if line not in changed_files:
                        changed_files.append(line)

            if self.verbose:
                print(f"📝 Found {len(changed_files)} changed Python files")
                for f in changed_files:
                    print(f"   - {f}")

            return changed_files

        except subprocess.CalledProcessError as e:
            print(f"⚠️  Error getting changed files: {e}")
            return []

    def get_module_from_path(self, file_path: str) -> str:
        """Convert file path to Python module path"""
        # Remove .py extension and convert slashes to dots
        module_path = file_path.replace('.py', '').replace('/', '.')
        return module_path

    def analyze_imports(self, file_path: Path) -> Set[str]:
        """Analyze imports in a Python file using AST - returns full module paths"""
        if not file_path.exists():
            return set()

        # Check cache first
        cache_key = str(file_path)
        if cache_key in self._import_cache:
            return self._import_cache[cache_key]

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=str(file_path))
            imports = set()

            for node in ast.walk(tree):
                # Handle: import foo, import foo.bar, import foo.bar.baz
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        # Store full module path, not just first component
                        imports.add(alias.name)

                        # Also add all parent module paths for matching
                        parts = alias.name.split('.')
                        for i in range(1, len(parts) + 1):
                            imports.add('.'.join(parts[:i]))

                # Handle: from foo.bar import baz
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        # Store full module path
                        imports.add(node.module)

                        # Also add all parent module paths for matching
                        parts = node.module.split('.')
                        for i in range(1, len(parts) + 1):
                            imports.add('.'.join(parts[:i]))

            self._import_cache[cache_key] = imports
            return imports

        except (SyntaxError, UnicodeDecodeError) as e:
            if self.verbose:
                print(f"⚠️  Could not parse {file_path}: {e}")
            return set()

    def build_dependency_graph(self):
        """Build a graph of which tests depend on which source files"""
        print("🔍 Building dependency graph...")

        # Find all test files
        test_files = list(self.test_dir.rglob("test_*.py"))

        for test_file in test_files:
            imports = self.analyze_imports(test_file)

            # Map imports to actual source files
            for imported_module in imports:
                # Check if this is a verenigingen module
                if imported_module == 'verenigingen' or imported_module.startswith('verenigingen.'):
                    self._dependency_graph[str(test_file)].add(imported_module)

        if self.verbose:
            print(f"📊 Analyzed {len(test_files)} test files")
            print(f"📈 Found {len(self._dependency_graph)} test dependencies")

    def find_impacted_tests(self, changed_files: List[str]) -> Set[str]:
        """Find all tests that are impacted by the changed files - with precision matching"""
        impacted_tests = set()

        # Build dependency graph if not already built
        if not self._dependency_graph:
            self.build_dependency_graph()

        # Convert changed files to exact module names (no parent modules)
        changed_modules = set()
        for file_path in changed_files:
            module = self.get_module_from_path(file_path)
            changed_modules.add(module)

        if self.verbose:
            print(f"\n🎯 Changed modules (exact):")
            for mod in sorted(changed_modules):
                print(f"   - {mod}")

        # Find tests that import the exact changed module or a submodule
        # Use precise matching: test must import specifically this module
        for test_file, dependencies in self._dependency_graph.items():
            matched = False
            for changed_module in changed_modules:
                # Match if test imports exactly this module OR a more specific submodule
                # Example: changed "verenigingen.doctype.member.member"
                #   Matches: "verenigingen.doctype.member.member" ✓
                #   Matches: "verenigingen.doctype.member.member.Member" ✓
                #   Does NOT match: "verenigingen.doctype.member" ✗
                #   Does NOT match: "verenigingen" ✗

                for dep in dependencies:
                    # Exact match or submodule of changed module
                    if dep == changed_module or dep.startswith(changed_module + '.'):
                        matched = True
                        if self.verbose:
                            print(f"   ✓ {Path(test_file).name} imports {dep}")
                        break

                if matched:
                    impacted_tests.add(test_file)
                    break

        # Also include direct test files for changed source files (by naming convention)
        for changed_file in changed_files:
            base_name = Path(changed_file).stem

            # Search for matching test files by name
            potential_test_patterns = [
                f"test_{base_name}.py",
                f"test_{base_name}_*.py",
                f"*_test_{base_name}.py",
            ]

            for pattern in potential_test_patterns:
                for test_file in self.test_dir.rglob(pattern):
                    if str(test_file) not in impacted_tests:
                        if self.verbose:
                            print(f"   ✓ {Path(test_file).name} matches naming pattern for {base_name}")
                        impacted_tests.add(str(test_file))

        return impacted_tests

    def generate_test_command(self, test_files: Set[str]) -> str:
        """Generate bench command to run the impacted tests"""
        if not test_files:
            return None

        # Convert file paths to test module paths for bench
        test_modules = []
        for test_file in sorted(test_files):
            # Convert: /path/to/verenigingen/tests/test_foo.py
            # To: verenigingen.tests.test_foo
            rel_path = Path(test_file).relative_to(self.repo_path)
            module = self.get_module_from_path(str(rel_path))
            test_modules.append(module)

        # Generate bench command
        if len(test_modules) == 1:
            return f"bench --site dev.veganisme.net run-tests --module {test_modules[0]}"
        else:
            # For multiple modules, run them sequentially
            commands = []
            for module in test_modules:
                commands.append(f"bench --site dev.veganisme.net run-tests --module {module}")
            return " && ".join(commands)

    def analyze_and_report(self, since: str = "HEAD~1") -> Dict:
        """Analyze changes and generate comprehensive report"""
        print("🔬 Test Impact Analysis")
        print("=" * 60)

        # Get changed files
        changed_files = self.get_changed_files(since)

        if not changed_files:
            print("\n✅ No Python files changed - no tests to run!")
            return {
                "changed_files": [],
                "impacted_tests": [],
                "command": None
            }

        print(f"\n📝 Changed files: {len(changed_files)}")
        for f in changed_files:
            print(f"   - {f}")

        # Find impacted tests
        impacted_tests = self.find_impacted_tests(changed_files)

        print(f"\n🎯 Impacted tests: {len(impacted_tests)}")
        if impacted_tests:
            for test in sorted(impacted_tests):
                rel_path = Path(test).relative_to(self.repo_path)
                print(f"   - {rel_path}")
        else:
            print("   (none)")

        # Generate command
        command = self.generate_test_command(impacted_tests)

        if command:
            print(f"\n💡 Run impacted tests with:")
            print(f"   {command}")

        print("\n" + "=" * 60)

        return {
            "changed_files": changed_files,
            "impacted_tests": list(impacted_tests),
            "command": command
        }


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze code changes and determine which tests to run"
    )
    parser.add_argument(
        "--since",
        default="HEAD~1",
        help="Git reference to compare against (default: HEAD~1)"
    )
    parser.add_argument(
        "--branch",
        help="Compare against a specific branch"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Automatically run the impacted tests"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed analysis"
    )

    args = parser.parse_args()

    # Determine comparison point
    since = args.branch if args.branch else args.since

    # Run analysis
    analyzer = TestImpactAnalyzer(verbose=args.verbose)
    result = analyzer.analyze_and_report(since=since)

    # Run tests if requested
    if args.run and result["command"]:
        print("\n🚀 Running impacted tests...")
        exit_code = os.system(result["command"])
        sys.exit(exit_code >> 8)  # Extract actual exit code

    # Exit with appropriate code
    if result["impacted_tests"]:
        sys.exit(1)  # Tests need to be run
    else:
        sys.exit(0)  # No tests to run


if __name__ == "__main__":
    main()
