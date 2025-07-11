#!/usr/bin/env python3
"""
Regression Test Runner for Verenigingen
Automatically detects changes and runs appropriate regression tests
"""

import json
import subprocess
import sys
from pathlib import Path

from frappe.utils import now


class RegressionTestRunner:
    def __init__(self):
        self.app_path = Path(__file__).parent
        self.test_results = {}
        self.changed_files = []

    def detect_changes(self, base_branch="main"):
        """Detect changed files using git diff"""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
                capture_output=True,
                text=True,
                cwd=self.app_path,
            )

            if result.returncode == 0:
                self.changed_files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
                return self.changed_files
        except Exception as e:
            print(f"Error detecting changes: {e}")
            return []

    def categorize_changes(self):
        """Categorize changes to determine which test suites to run"""
        categories = {
            "core_models": [],
            "api_endpoints": [],
            "frontend": [],
            "reports": [],
            "workflows": [],
            "security": [],
            "configuration": [],
            "js_api_integration": [],
        }

        for file_path in self.changed_files:
            if "doctype" in file_path and file_path.endswith(".py"):
                categories["core_models"].append(file_path)
            elif "/api/" in file_path:
                categories["api_endpoints"].append(file_path)
                # API changes also trigger JS API integration tests
                categories["js_api_integration"].append(file_path)
            elif file_path.endswith((".js", ".html", ".css")):
                categories["frontend"].append(file_path)
                # JavaScript changes trigger JS API integration tests
                if file_path.endswith(".js"):
                    categories["js_api_integration"].append(file_path)
            elif "/report/" in file_path:
                categories["reports"].append(file_path)
            elif "termination" in file_path or "workflow" in file_path:
                categories["workflows"].append(file_path)
            elif "permission" in file_path or "auth" in file_path:
                categories["security"].append(file_path)
            elif file_path.endswith((".json", ".yaml", "hooks.py")):
                categories["configuration"].append(file_path)

        return categories

    def run_targeted_tests(self, categories):
        """Run targeted regression tests based on changed categories"""
        test_commands = []

        # Core model changes - run comprehensive tests
        if categories["core_models"]:
            test_commands.extend(
                [
                    "python verenigingen/tests/test_runner.py all",
                    "bench run-tests --app verenigingen --module verenigingen.tests.test_termination_system",
                ]
            )

        # API changes - run API and integration tests
        if categories["api_endpoints"]:
            test_commands.extend(
                [
                    "python run_volunteer_portal_tests.py --suite integration",
                    "bench run-tests --app verenigingen --module verenigingen.tests.test_volunteer_portal_working",
                ]
            )

        # Workflow changes - run workflow-specific tests
        if categories["workflows"]:
            test_commands.extend(
                [
                    "python verenigingen/tests/test_runner.py diagnostic",
                    "bench run-tests --app verenigingen --module verenigingen.tests.test_termination_system",
                ]
            )

        # Security changes - always run security suite
        if categories["security"] or categories["configuration"]:
            test_commands.append("python run_volunteer_portal_tests.py --suite security")

        # Frontend changes - run core functionality tests
        if categories["frontend"]:
            test_commands.append("python run_volunteer_portal_tests.py --suite core")

        # Report changes - test reports
        if categories["reports"]:
            test_commands.append("python verenigingen/tests/test_runner.py smoke")

        # JavaScript API integration changes - run integration tests
        if categories["js_api_integration"]:
            test_commands.append("bench run-tests --app verenigingen --module verenigingen.tests.test_javascript_api_integration")

        # Always run smoke tests as baseline
        if not any(categories.values()):
            test_commands.append("python verenigingen/tests/test_runner.py smoke")

        return self.execute_test_commands(test_commands)

    def execute_test_commands(self, commands):
        """Execute test commands and collect results"""
        results = {}

        for cmd in commands:
            print(f"\n🧪 Running: {cmd}")
            try:
                result = subprocess.run(
                    cmd.split(),
                    capture_output=True,
                    text=True,
                    cwd=self.app_path,
                    timeout=300,  # 5 minute timeout per test suite
                )

                success = result.returncode == 0
                results[cmd] = {
                    "success": success,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                }

                status = "✅ PASSED" if success else "❌ FAILED"
                print(f"{status}: {cmd}")

                if not success:
                    print(f"Error output: {result.stderr}")

            except subprocess.TimeoutExpired:
                results[cmd] = {"success": False, "error": "Test suite timed out", "returncode": -1}
                print(f"⏰ TIMEOUT: {cmd}")

            except Exception as e:
                results[cmd] = {"success": False, "error": str(e), "returncode": -2}
                print(f"💥 ERROR: {cmd} - {e}")

        return results

    def generate_report(self, test_results, categories):
        """Generate comprehensive regression test report"""
        report = {
            "timestamp": now(),
            "changed_files": self.changed_files,
            "categories": categories,
            "test_results": test_results,
            "summary": {
                "total_tests": len(test_results),
                "passed": sum(1 for r in test_results.values() if r["success"]),
                "failed": sum(1 for r in test_results.values() if not r["success"]),
            },
        }

        # Save report
        report_file = self.app_path / f"regression_report_{now().replace(' ', '_').replace(':', '-')}.json"
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2, default=str)

        return report, report_file

    def run_regression_suite(self, base_branch="main"):
        """Run complete regression test suite"""
        print("🔍 Detecting changes...")
        self.detect_changes(base_branch)

        if not self.changed_files:
            print("No changes detected, running smoke tests only")
            categories = {}
        else:
            print(f"📁 Found {len(self.changed_files)} changed files")
            categories = self.categorize_changes()

        print("\n📊 Change categories:")
        for category, files in categories.items():
            if files:
                print(f"  {category}: {len(files)} files")

        print("\n🧪 Running targeted regression tests...")
        test_results = self.run_targeted_tests(categories)

        report, report_file = self.generate_report(test_results, categories)

        print(f"\n📋 Regression Test Summary:")
        print(f"  Total tests: {report['summary']['total_tests']}")
        print(f"  Passed: {report['summary']['passed']}")
        print(f"  Failed: {report['summary']['failed']}")
        print(f"  Report saved: {report_file}")

        # Return non-zero exit code if any tests failed
        if report["summary"]["failed"] > 0:
            print("\n❌ Regression tests failed!")
            return 1
        else:
            print("\n✅ All regression tests passed!")
            return 0


def main():
    if len(sys.argv) > 1:
        base_branch = sys.argv[1]
    else:
        base_branch = "main"

    runner = RegressionTestRunner()
    exit_code = runner.run_regression_suite(base_branch)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
