#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coverage Report Generator
Generates comprehensive test coverage reports for the Verenigingen app
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path
import argparse


class CoverageReporter:
    """Generate and track test coverage reports"""
    
    def __init__(self, app_path=None):
        self.app_path = app_path or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.coverage_dir = os.path.join(self.app_path, "coverage_reports")
        self.ensure_coverage_dir()
        
    def ensure_coverage_dir(self):
        """Ensure coverage directory exists"""
        Path(self.coverage_dir).mkdir(parents=True, exist_ok=True)
        
    def run_python_coverage(self):
        """Run Python test coverage"""
        print("🐍 Running Python test coverage...")
        
        cmd = [
            "coverage", "run",
            "-m", "pytest",
            "verenigingen/tests",
            "--verbose"
        ]
        
        try:
            subprocess.run(cmd, check=True, cwd=self.app_path)
            
            # Generate reports
            subprocess.run(["coverage", "html"], cwd=self.app_path)
            subprocess.run(["coverage", "xml"], cwd=self.app_path)
            subprocess.run(["coverage", "json"], cwd=self.app_path)
            
            # Get coverage percentage
            result = subprocess.run(
                ["coverage", "report", "--format=json"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            if result.stdout:
                coverage_data = json.loads(result.stdout)
                return coverage_data.get("totals", {}).get("percent_covered", 0)
            
        except subprocess.CalledProcessError as e:
            print(f"❌ Error running Python coverage: {e}")
            return 0
            
    def run_javascript_coverage(self):
        """Run JavaScript test coverage"""
        print("🌐 Running JavaScript test coverage...")
        
        package_json_path = os.path.join(self.app_path, "package.json")
        
        # Check if package.json exists, if not create it
        if not os.path.exists(package_json_path):
            self.create_package_json()
            
        try:
            # Install dependencies if needed
            subprocess.run(["npm", "install"], cwd=self.app_path)
            
            # Run Jest with coverage
            result = subprocess.run(
                ["npm", "test", "--", "--coverage", "--json"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            if result.stdout:
                coverage_data = json.loads(result.stdout)
                summary = coverage_data.get("coverageMap", {})
                # Calculate average coverage
                if summary:
                    total_coverage = 0
                    file_count = 0
                    for file_data in summary.values():
                        metrics = file_data.get("s", {})
                        if metrics:
                            covered = sum(1 for v in metrics.values() if v > 0)
                            total = len(metrics)
                            if total > 0:
                                total_coverage += (covered / total) * 100
                                file_count += 1
                    
                    return total_coverage / file_count if file_count > 0 else 0
                    
        except subprocess.CalledProcessError as e:
            print(f"❌ Error running JavaScript coverage: {e}")
            return 0
            
        return 0
        
    def create_package_json(self):
        """Create package.json if it doesn't exist"""
        package_json = {
            "name": "verenigingen",
            "version": "1.0.0",
            "description": "Verenigingen app tests",
            "scripts": {
                "test": "jest",
                "test:coverage": "jest --coverage",
                "test:watch": "jest --watch"
            },
            "devDependencies": {
                "@babel/preset-env": "^7.20.0",
                "babel-jest": "^29.3.0",
                "identity-obj-proxy": "^3.0.0",
                "jest": "^29.3.0",
                "jest-environment-jsdom": "^29.3.0",
                "jest-junit": "^15.0.0"
            }
        }
        
        with open(os.path.join(self.app_path, "package.json"), "w") as f:
            json.dump(package_json, f, indent=2)
            
    def generate_badge(self, coverage_percent):
        """Generate coverage badge"""
        color = "red"
        if coverage_percent >= 80:
            color = "brightgreen"
        elif coverage_percent >= 60:
            color = "yellow"
        elif coverage_percent >= 40:
            color = "orange"
            
        badge_url = f"https://img.shields.io/badge/coverage-{coverage_percent:.1f}%25-{color}"
        return badge_url
        
    def generate_summary_report(self, py_coverage, js_coverage):
        """Generate summary report"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_coverage = (py_coverage + js_coverage) / 2 if js_coverage > 0 else py_coverage
        
        report = f"""# Verenigingen Test Coverage Report
Generated: {timestamp}

## Summary
- **Total Coverage**: {total_coverage:.1f}%
- **Python Coverage**: {py_coverage:.1f}%
- **JavaScript Coverage**: {js_coverage:.1f}%

## Coverage Badge
![Coverage]({self.generate_badge(total_coverage)})

## Detailed Reports
- [Python HTML Report](./htmlcov/index.html)
- [JavaScript HTML Report](./coverage/lcov-report/index.html)

## Coverage Trends
"""
        
        # Save historical data
        history_file = os.path.join(self.coverage_dir, "coverage_history.json")
        history = []
        
        if os.path.exists(history_file):
            with open(history_file, "r") as f:
                history = json.load(f)
                
        history.append({
            "timestamp": timestamp,
            "total": total_coverage,
            "python": py_coverage,
            "javascript": js_coverage
        })
        
        # Keep last 30 entries
        history = history[-30:]
        
        with open(history_file, "w") as f:
            json.dump(history, f, indent=2)
            
        # Add trend to report
        if len(history) > 1:
            trend = history[-1]["total"] - history[-2]["total"]
            trend_symbol = "📈" if trend > 0 else "📉" if trend < 0 else "➡️"
            report += f"\nLatest trend: {trend_symbol} {abs(trend):.1f}%\n"
            
        # Save report
        report_file = os.path.join(self.coverage_dir, "COVERAGE.md")
        with open(report_file, "w") as f:
            f.write(report)
            
        print(f"\n✅ Coverage report saved to: {report_file}")
        print(f"📊 Total coverage: {total_coverage:.1f}%")
        
        return total_coverage
        
    def check_thresholds(self, coverage, threshold=70):
        """Check if coverage meets threshold"""
        if coverage < threshold:
            print(f"\n❌ Coverage {coverage:.1f}% is below threshold {threshold}%")
            return False
        else:
            print(f"\n✅ Coverage {coverage:.1f}% meets threshold {threshold}%")
            return True
            
    def run_full_coverage(self, threshold=70):
        """Run full coverage analysis"""
        print("🚀 Starting coverage analysis for Vereiningen app...\n")
        
        # Run Python coverage
        py_coverage = self.run_python_coverage()
        print(f"Python coverage: {py_coverage:.1f}%")
        
        # Run JavaScript coverage
        js_coverage = self.run_javascript_coverage()
        print(f"JavaScript coverage: {js_coverage:.1f}%")
        
        # Generate summary
        total_coverage = self.generate_summary_report(py_coverage, js_coverage)
        
        # Check thresholds
        return self.check_thresholds(total_coverage, threshold)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Generate test coverage reports")
    parser.add_argument(
        "--threshold",
        type=int,
        default=70,
        help="Coverage threshold percentage (default: 70)"
    )
    parser.add_argument(
        "--python-only",
        action="store_true",
        help="Run Python coverage only"
    )
    parser.add_argument(
        "--javascript-only",
        action="store_true",
        help="Run JavaScript coverage only"
    )
    
    args = parser.parse_args()
    
    reporter = CoverageReporter()
    
    if args.python_only:
        coverage = reporter.run_python_coverage()
        print(f"\nPython coverage: {coverage:.1f}%")
        sys.exit(0 if reporter.check_thresholds(coverage, args.threshold) else 1)
        
    elif args.javascript_only:
        coverage = reporter.run_javascript_coverage()
        print(f"\nJavaScript coverage: {coverage:.1f}%")
        sys.exit(0 if reporter.check_thresholds(coverage, args.threshold) else 1)
        
    else:
        success = reporter.run_full_coverage(args.threshold)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()