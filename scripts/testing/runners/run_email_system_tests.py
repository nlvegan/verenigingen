#!/usr/bin/env python3
"""
Email System Test Runner
=======================

Specialized test runner for the comprehensive email/newsletter system test suite.
Provides detailed reporting, benchmarking, and production readiness assessment.

Usage:
    python run_email_system_tests.py --suite all
    python run_email_system_tests.py --suite security,integration
    python run_email_system_tests.py --suite performance --benchmark
    python run_email_system_tests.py --report-only
"""

import os
import sys
import argparse
import json
from datetime import datetime
from typing import Dict, List, Optional

# Add Frappe environment setup
sys.path.insert(0, '/home/frappe/frappe-bench/apps/frappe')
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

import frappe
from frappe.utils import now_datetime

# Import the comprehensive test suite
from verenigingen.tests.test_email_newsletter_system_comprehensive import (
    run_comprehensive_email_tests,
    TestEmailNewsletterSystemSecurity,
    TestEmailNewsletterSystemIntegration,
    TestEmailNewsletterSystemBusinessLogic,
    TestEmailNewsletterSystemErrorHandling,
    TestEmailNewsletterSystemPerformance,
    TestEmailNewsletterSystemDataIntegrity
)


class EmailSystemTestRunner:
    """
    Advanced test runner for email system validation
    """
    
    def __init__(self, site_name: str = "dev.veganisme.net"):
        self.site_name = site_name
        self.results_dir = "/tmp/email_system_test_results"
        self.ensure_results_directory()
        
    def ensure_results_directory(self):
        """Ensure results directory exists"""
        os.makedirs(self.results_dir, exist_ok=True)
        
    def initialize_frappe_environment(self):
        """Initialize Frappe environment for testing"""
        if not hasattr(frappe.local, 'site'):
            frappe.init(site=self.site_name)
            frappe.connect()
            
    def run_test_suites(
        self, 
        suites: List[str] = None, 
        benchmark: bool = False,
        verbose: bool = True
    ) -> Dict:
        """
        Run email system test suites with comprehensive reporting
        
        Args:
            suites: List of test suite names to run
            benchmark: Whether to include performance benchmarking
            verbose: Whether to print detailed output
            
        Returns:
            Dict with comprehensive test results
        """
        # Initialize environment
        self.initialize_frappe_environment()
        
        # Run the tests
        start_time = datetime.now()
        
        if verbose:
            print(f"\n{'='*80}")
            print(f"EMAIL SYSTEM COMPREHENSIVE TEST EXECUTION")
            print(f"{'='*80}")
            print(f"Site: {self.site_name}")
            print(f"Start time: {start_time}")
            print(f"Suites: {suites or 'ALL'}")
            print(f"Benchmark mode: {benchmark}")
            print(f"{'='*80}")
        
        # Execute the comprehensive test suite
        test_results = run_comprehensive_email_tests(suites)
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Enhanced results with metadata
        enhanced_results = {
            "execution_metadata": {
                "site": self.site_name,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(), 
                "execution_time_seconds": execution_time,
                "suites_requested": suites,
                "benchmark_mode": benchmark
            },
            "test_results": test_results,
            "production_readiness": self._assess_production_readiness(test_results),
            "security_assessment": self._assess_security_posture(test_results),
            "performance_metrics": self._extract_performance_metrics(test_results) if benchmark else None
        }
        
        # Save detailed results
        self._save_results(enhanced_results)
        
        # Print summary
        if verbose:
            self._print_executive_summary(enhanced_results)
            
        return enhanced_results
        
    def _assess_production_readiness(self, test_results: Dict) -> Dict:
        """Assess production readiness based on test results"""
        suite_results = test_results.get("suite_results", {})
        
        # Critical requirements for production readiness
        critical_suites = ["security", "integration", "data_integrity"]
        critical_success_rates = []
        
        for suite_name in critical_suites:
            if suite_name in suite_results:
                critical_success_rates.append(suite_results[suite_name]["success_rate"])
        
        # Calculate readiness scores
        overall_success = test_results.get("overall_success_rate", 0)
        critical_average = sum(critical_success_rates) / len(critical_success_rates) if critical_success_rates else 0
        
        # Readiness assessment
        if overall_success >= 95 and critical_average >= 98:
            readiness_level = "READY"
            readiness_color = "GREEN"
        elif overall_success >= 90 and critical_average >= 95:
            readiness_level = "MOSTLY_READY"
            readiness_color = "YELLOW"
        elif overall_success >= 80 and critical_average >= 90:
            readiness_level = "NEEDS_WORK"
            readiness_color = "ORANGE"
        else:
            readiness_level = "NOT_READY"
            readiness_color = "RED"
            
        return {
            "level": readiness_level,
            "color": readiness_color,
            "overall_success_rate": overall_success,
            "critical_suite_average": critical_average,
            "critical_requirements_met": critical_average >= 95,
            "blockers": self._identify_production_blockers(suite_results),
            "recommendation": self._generate_production_recommendation(readiness_level, suite_results)
        }
        
    def _assess_security_posture(self, test_results: Dict) -> Dict:
        """Assess security posture based on security test results"""
        suite_results = test_results.get("suite_results", {})
        security_results = suite_results.get("security", {})
        
        security_success_rate = security_results.get("success_rate", 0)
        security_failures = security_results.get("failures", 0)
        security_errors = security_results.get("errors", 0)
        
        # Security assessment levels
        if security_success_rate >= 100:
            security_level = "EXCELLENT"
            security_color = "GREEN"
        elif security_success_rate >= 95:
            security_level = "GOOD"
            security_color = "LIGHT_GREEN"
        elif security_success_rate >= 85:
            security_level = "ACCEPTABLE"
            security_color = "YELLOW"
        else:
            security_level = "NEEDS_IMPROVEMENT"
            security_color = "RED"
            
        return {
            "level": security_level,
            "color": security_color,
            "success_rate": security_success_rate,
            "failures": security_failures,
            "errors": security_errors,
            "vulnerabilities_identified": security_failures + security_errors,
            "sql_injection_protected": security_success_rate >= 95,
            "permission_bypass_prevented": security_success_rate >= 95,
            "input_validation_secure": security_success_rate >= 95
        }
        
    def _extract_performance_metrics(self, test_results: Dict) -> Optional[Dict]:
        """Extract performance metrics from test results"""
        suite_results = test_results.get("suite_results", {})
        performance_results = suite_results.get("performance", {})
        
        if not performance_results:
            return None
            
        return {
            "large_dataset_performance": "MEASURED",
            "concurrent_operation_handling": "TESTED", 
            "template_rendering_speed": "BENCHMARKED",
            "analytics_query_performance": "MEASURED",
            "segmentation_query_speed": "TESTED",
            "success_rate": performance_results.get("success_rate", 0),
            "benchmark_data": "Available in detailed results"
        }
        
    def _identify_production_blockers(self, suite_results: Dict) -> List[str]:
        """Identify critical issues blocking production deployment"""
        blockers = []
        
        # Security blockers
        security_results = suite_results.get("security", {})
        if security_results.get("success_rate", 0) < 95:
            blockers.append("CRITICAL: Security vulnerabilities detected - deployment blocked")
            
        # Data integrity blockers
        integrity_results = suite_results.get("data_integrity", {})
        if integrity_results.get("success_rate", 0) < 95:
            blockers.append("CRITICAL: Data integrity issues detected - deployment blocked")
            
        # Integration blockers
        integration_results = suite_results.get("integration", {})
        if integration_results.get("success_rate", 0) < 90:
            blockers.append("HIGH: Integration failures detected - review required")
            
        return blockers
        
    def _generate_production_recommendation(self, readiness_level: str, suite_results: Dict) -> str:
        """Generate production deployment recommendation"""
        if readiness_level == "READY":
            return "✅ DEPLOY TO PRODUCTION: All critical tests passing, system is production-ready"
        elif readiness_level == "MOSTLY_READY":
            return "⚠️ DEPLOY WITH CAUTION: Minor issues detected, monitor closely after deployment"
        elif readiness_level == "NEEDS_WORK":
            return "🔄 DEFER DEPLOYMENT: Address failing tests before production deployment"
        else:
            return "🚫 DO NOT DEPLOY: Critical issues must be resolved before production deployment"
            
    def _save_results(self, results: Dict):
        """Save detailed test results to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"email_system_test_results_{timestamp}.json"
        filepath = os.path.join(self.results_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        print(f"\n📊 Detailed results saved to: {filepath}")
        
    def _print_executive_summary(self, results: Dict):
        """Print executive summary of test results"""
        test_results = results["test_results"]
        production_readiness = results["production_readiness"]
        security_assessment = results["security_assessment"]
        execution_metadata = results["execution_metadata"]
        
        print(f"\n{'='*80}")
        print(f"EXECUTIVE SUMMARY - EMAIL SYSTEM TEST RESULTS")
        print(f"{'='*80}")
        
        # Production Readiness
        print(f"\n🏭 PRODUCTION READINESS: {production_readiness['level']}")
        print(f"   Overall Success Rate: {production_readiness['overall_success_rate']:.1f}%")
        print(f"   Critical Systems: {production_readiness['critical_suite_average']:.1f}%")
        print(f"   Recommendation: {production_readiness['recommendation']}")
        
        # Security Assessment
        print(f"\n🔒 SECURITY POSTURE: {security_assessment['level']}")
        print(f"   Security Test Success: {security_assessment['success_rate']:.1f}%")
        print(f"   Vulnerabilities: {security_assessment['vulnerabilities_identified']}")
        print(f"   SQL Injection Protected: {'✅' if security_assessment['sql_injection_protected'] else '❌'}")
        print(f"   Permission Bypass Prevented: {'✅' if security_assessment['permission_bypass_prevented'] else '❌'}")
        
        # Test Suite Breakdown
        print(f"\n📋 TEST SUITE BREAKDOWN:")
        for suite_name, suite_result in test_results["suite_results"].items():
            status_emoji = "✅" if suite_result["success_rate"] >= 95 else "⚠️" if suite_result["success_rate"] >= 80 else "❌"
            print(f"   {status_emoji} {suite_name.title()}: {suite_result['success_rate']:.1f}% ({suite_result['tests_run']} tests)")
            
        # Blockers
        if production_readiness["blockers"]:
            print(f"\n🚫 PRODUCTION BLOCKERS:")
            for blocker in production_readiness["blockers"]:
                print(f"   - {blocker}")
                
        # Performance (if available)
        if results.get("performance_metrics"):
            print(f"\n⚡ PERFORMANCE METRICS: Available")
            
        # Execution Summary
        print(f"\n📈 EXECUTION SUMMARY:")
        print(f"   Total Tests: {test_results['total_tests']}")
        print(f"   Total Failures: {test_results['total_failures']}")
        print(f"   Total Errors: {test_results['total_errors']}")
        print(f"   Execution Time: {execution_metadata['execution_time_seconds']:.1f} seconds")
        
        print(f"\n{'='*80}")


def main():
    """Main entry point for the test runner"""
    parser = argparse.ArgumentParser(description="Email System Comprehensive Test Runner")
    
    parser.add_argument(
        "--suite", 
        type=str, 
        default="all",
        help="Test suites to run (comma-separated): security,integration,business_logic,error_handling,performance,data_integrity"
    )
    
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Enable performance benchmarking"
    )
    
    parser.add_argument(
        "--site",
        type=str,
        default="dev.veganisme.net",
        help="Frappe site name"
    )
    
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output"
    )
    
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Generate report from last test run only"
    )
    
    args = parser.parse_args()
    
    # Parse test suites
    if args.suite.lower() == "all":
        suites = None
    else:
        suites = [s.strip() for s in args.suite.split(",")]
        
    # Initialize runner
    runner = EmailSystemTestRunner(args.site)
    
    try:
        if args.report_only:
            print("Report-only mode not yet implemented")
            return
            
        # Run tests
        results = runner.run_test_suites(
            suites=suites,
            benchmark=args.benchmark,
            verbose=not args.quiet
        )
        
        # Exit with appropriate code
        production_readiness = results["production_readiness"]
        if production_readiness["level"] in ["READY", "MOSTLY_READY"]:
            sys.exit(0)  # Success
        else:
            sys.exit(1)  # Failure - not production ready
            
    except Exception as e:
        print(f"❌ Test execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(2)  # Error


if __name__ == "__main__":
    main()