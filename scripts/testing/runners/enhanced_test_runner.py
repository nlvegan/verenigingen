#!/usr/bin/env python3
"""
Enhanced Test Runner - Phase 1 Testing Infrastructure Enhancements

Provides comprehensive test execution with coverage reporting, performance analysis,
and edge case tracking integrated with the existing VereningingenTestCase infrastructure.

Usage Examples:
    python enhanced_test_runner.py --coverage --html-report
    python enhanced_test_runner.py --performance-report
    python enhanced_test_runner.py --edge-case-summary
    python enhanced_test_runner.py --suite comprehensive --all-reports
"""

import argparse
import os
import sys
import webbrowser
from pathlib import Path

# Add the apps directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Import frappe and our enhanced test infrastructure
import frappe


class EnhancedTestRunner:
    """
    Command-line interface for the enhanced testing infrastructure.
    Integrates with existing VereningingenTestCase and provides new reporting capabilities.
    """
    
    def __init__(self):
        self.test_results_dir = Path("/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results")
        self.test_results_dir.mkdir(exist_ok=True)
        
    def run_with_options(self, args):
        """Run tests based on command line arguments"""
        print("🧪 Enhanced Verenigingen Test Runner - Phase 1")
        print("=" * 60)
        
        # Determine which test suite to run
        if args.suite == "quick":
            result = self._run_quick_tests(args)
        elif args.suite == "comprehensive":
            result = self._run_comprehensive_tests(args)
        elif args.suite == "performance":
            result = self._run_performance_tests(args)
        elif args.suite == "edge_cases":
            result = self._run_edge_case_tests(args)
        elif args.suite == "all":
            result = self._run_all_tests_with_reports(args)
        else:
            print(f"❌ Unknown test suite: {args.suite}")
            return False
            
        # Generate additional reports if requested
        if args.all_reports or args.coverage or args.performance_report or args.edge_case_summary:
            self._generate_additional_reports(args, result)
            
        # Open HTML dashboard if requested
        if args.html_report:
            self._open_html_dashboard()
            
        return result.get("success", False)
        
    def _run_quick_tests(self, args):
        """Run quick test suite with optional reporting"""
        print("🚀 Running Quick Test Suite...")
        
        return frappe.get_attr("verenigingen.tests.utils.test_runner.run_quick_tests")(
            coverage=args.coverage or args.all_reports,
            performance=args.performance_report or args.all_reports
        )
        
    def _run_comprehensive_tests(self, args):
        """Run comprehensive test suite with full reporting"""
        print("🚀 Running Comprehensive Test Suite...")
        
        return frappe.get_attr("verenigingen.tests.utils.test_runner.run_comprehensive_tests")(
            coverage=args.coverage or args.all_reports,
            performance=args.performance_report or args.all_reports,
            html_report=args.html_report or args.all_reports
        )
        
    def _run_performance_tests(self, args):
        """Run performance-focused test analysis"""
        print("⚡ Running Performance Test Analysis...")
        
        return frappe.get_attr("verenigingen.tests.utils.test_runner.run_performance_test_analysis")()
        
    def _run_edge_case_tests(self, args):
        """Run edge case validation tests"""
        print("🎯 Running Edge Case Validation...")
        
        return frappe.get_attr("verenigingen.tests.utils.test_runner.run_edge_case_validation")()
        
    def _run_all_tests_with_reports(self, args):
        """Run all tests with comprehensive reporting"""
        print("🚀 Running All Tests with Comprehensive Reporting...")
        
        return frappe.get_attr("verenigingen.tests.utils.test_runner.run_tests_with_coverage_dashboard")()
        
    def _generate_additional_reports(self, args, test_result):
        """Generate additional reports based on arguments"""
        print("\\n📊 Generating Additional Reports...")
        
        if args.coverage or args.all_reports:
            print("   📈 Generating coverage dashboard...")
            frappe.get_attr("verenigingen.tests.utils.coverage_reporter.generate_coverage_dashboard")()
            
        if args.performance_report or args.all_reports:
            print("   ⚡ Performance analysis completed (included in test run)")
            
        if args.edge_case_summary or args.all_reports:
            print("   🎯 Edge case summary completed (included in test run)")
            
        print("✅ All reports generated successfully!")
        
    def _open_html_dashboard(self):
        """Open the HTML dashboard in the default browser"""
        dashboard_path = self.test_results_dir / "coverage_dashboard.html"
        
        if dashboard_path.exists():
            print(f"🌐 Opening HTML dashboard: {dashboard_path}")
            try:
                webbrowser.open(f"file://{dashboard_path}")
            except Exception as e:
                print(f"⚠️ Could not open browser automatically: {e}")
                print(f"📄 Manual access: file://{dashboard_path}")
        else:
            print("⚠️ HTML dashboard not found. Run with --coverage to generate it.")
            
    def list_available_reports(self):
        """List all available reports in the test results directory"""
        print("📋 Available Test Reports:")
        print("=" * 40)
        
        report_files = {
            "coverage_dashboard.html": "📊 Coverage Dashboard (HTML)",
            "coverage_report.json": "📈 Coverage Report (JSON)",
            "performance_report.json": "⚡ Performance Analysis",
            "edge_case_summary.json": "🎯 Edge Case Coverage",
            "quick_tests.json": "🏃 Quick Test Results",
            "comprehensive_tests.json": "🔍 Comprehensive Test Results",
            "full_test_run.json": "📑 Complete Test Run"
        }
        
        found_reports = []
        for filename, description in report_files.items():
            filepath = self.test_results_dir / filename
            if filepath.exists():
                modified = filepath.stat().st_mtime
                import datetime
                mod_time = datetime.datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M")
                found_reports.append(f"  {description}")
                found_reports.append(f"    📁 {filepath}")
                found_reports.append(f"    🕐 Modified: {mod_time}")
                found_reports.append("")
                
        if found_reports:
            print("\\n".join(found_reports))
        else:
            print("  No reports found. Run tests with reporting options to generate reports.")
            
        print(f"\\n📁 Report Directory: {self.test_results_dir}")


def create_argument_parser():
    """Create command line argument parser"""
    parser = argparse.ArgumentParser(
        description="Enhanced Verenigingen Test Runner with Coverage and Performance Reporting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python enhanced_test_runner.py --suite quick --coverage
  python enhanced_test_runner.py --suite comprehensive --all-reports --html-report
  python enhanced_test_runner.py --suite performance
  python enhanced_test_runner.py --suite all --html-report
  python enhanced_test_runner.py --list-reports
        """
    )
    
    # Test suite selection
    parser.add_argument(
        "--suite",
        choices=["quick", "comprehensive", "performance", "edge_cases", "all"],
        default="comprehensive",
        help="Test suite to run (default: comprehensive)"
    )
    
    # Reporting options
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Generate test coverage report and dashboard"
    )
    
    parser.add_argument(
        "--performance-report",
        action="store_true",
        help="Generate detailed performance analysis"
    )
    
    parser.add_argument(
        "--edge-case-summary",
        action="store_true",
        help="Generate edge case coverage summary"
    )
    
    parser.add_argument(
        "--html-report",
        action="store_true",
        help="Generate HTML dashboard and open in browser"
    )
    
    parser.add_argument(
        "--all-reports",
        action="store_true",
        help="Generate all available reports (coverage, performance, edge cases)"
    )
    
    # Utility options
    parser.add_argument(
        "--list-reports",
        action="store_true",
        help="List all available test reports"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    return parser


def main():
    """Main entry point"""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    # Initialize Frappe environment
    try:
        if not frappe.local.db:
            frappe.init(site="dev.veganisme.net")
            frappe.connect()
    except Exception as e:
        print(f"❌ Failed to initialize Frappe environment: {e}")
        print("   Make sure you're running from the Frappe bench directory")
        return 1
        
    runner = EnhancedTestRunner()
    
    try:
        if args.list_reports:
            runner.list_available_reports()
            return 0
            
        success = runner.run_with_options(args)
        
        if success:
            print("\\n✅ All tests completed successfully!")
            return 0
        else:
            print("\\n❌ Some tests failed. Check the reports for details.")
            return 1
            
    except Exception as e:
        print(f"❌ Test runner error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1
    finally:
        if frappe.local.db:
            frappe.db.close()


if __name__ == "__main__":
    sys.exit(main())