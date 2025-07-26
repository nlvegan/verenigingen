"""
Test Coverage Dashboard and Reporter for Verenigingen Testing Infrastructure

Integrates with existing coverage.py usage and provides comprehensive HTML dashboard
for test results including coverage, performance metrics, and edge case tracking.
"""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import subprocess
import sys
import traceback

import frappe
from frappe.utils import now, get_datetime


class TestCoverageReporter:
    """
    Enhanced test coverage reporter that integrates with the existing 
    VereningingenTestCase infrastructure and provides comprehensive dashboards.
    """
    
    def __init__(self, output_dir: Optional[str] = None):
        """Initialize the coverage reporter"""
        self.output_dir = Path(output_dir or "/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Coverage data storage
        self.coverage_data = {}
        self.test_results = {}
        self.performance_metrics = {}
        self.edge_case_tracking = {}
        
        # Initialize tracking
        self.start_time = time.time()
        self.test_count = 0
        self.query_count = 0
        
    def track_test_execution(self, test_name: str, result: Dict[str, Any]):
        """Track individual test execution results"""
        self.test_results[test_name] = {
            "timestamp": now(),
            "status": result.get("status", "unknown"),
            "duration": result.get("duration", 0),
            "query_count": result.get("query_count", 0),
            "memory_usage": result.get("memory_usage", 0),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", [])
        }
        
        # Track performance metrics
        self._update_performance_metrics(test_name, result)
        
    def track_edge_case_coverage(self, test_name: str, edge_cases: List[str]):
        """Track edge case coverage for comprehensive testing"""
        if test_name not in self.edge_case_tracking:
            self.edge_case_tracking[test_name] = {
                "covered_cases": [],
                "total_cases": 0,
                "coverage_percentage": 0
            }
            
        self.edge_case_tracking[test_name]["covered_cases"].extend(edge_cases)
        self.edge_case_tracking[test_name]["total_cases"] = len(
            set(self.edge_case_tracking[test_name]["covered_cases"])
        )
        
    def generate_coverage_report(self, include_html: bool = True) -> Dict[str, Any]:
        """Generate comprehensive coverage report"""
        print("🔍 Generating test coverage report...")
        
        # Run coverage analysis using coverage.py
        coverage_data = self._run_coverage_analysis()
        
        # Compile comprehensive report
        report = {
            "timestamp": now(),
            "summary": self._generate_summary(),
            "coverage": coverage_data,
            "performance": self._generate_performance_report(),
            "edge_cases": self._generate_edge_case_report(),
            "test_results": self.test_results,
            "trends": self._generate_trend_analysis()
        }
        
        # Save JSON report
        json_path = self.output_dir / "coverage_report.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
            
        print(f"📊 JSON report saved: {json_path}")
        
        # Generate HTML dashboard if requested
        if include_html:
            html_path = self._generate_html_dashboard(report)
            print(f"🌐 HTML dashboard: {html_path}")
            
        return report
        
    def _run_coverage_analysis(self) -> Dict[str, Any]:
        """Run coverage.py analysis on the codebase"""
        try:
            # Run coverage with our test modules
            cmd = [
                sys.executable, "-m", "coverage", "run", 
                "--source=verenigingen",
                "--omit=*/tests/*,*/fixtures/*",
                "-m", "pytest", "verenigingen/tests/", "-v"
            ]
            
            # Use subprocess to capture coverage data
            result = subprocess.run(
                cmd, capture_output=True, text=True, 
                cwd="/home/frappe/frappe-bench/apps/verenigingen"
            )
            
            # Generate coverage report (handle different coverage.py versions)
            coverage_cmd = [sys.executable, "-m", "coverage", "json"]
            coverage_result = subprocess.run(
                coverage_cmd, capture_output=True, text=True,
                cwd="/home/frappe/frappe-bench/apps/verenigingen"
            )
            
            if coverage_result.returncode == 0:
                # Try to read from coverage.json file
                coverage_json_path = "/home/frappe/frappe-bench/apps/verenigingen/coverage.json"
                try:
                    with open(coverage_json_path, 'r') as f:
                        return json.load(f)
                except FileNotFoundError:
                    # If file doesn't exist, return from stdout
                    return json.loads(coverage_result.stdout) if coverage_result.stdout else {"files": {}, "totals": {"percent_covered": 0}}
            else:
                print(f"⚠️ Coverage analysis failed: {coverage_result.stderr}")
                return {"files": {}, "totals": {"percent_covered": 0}}
                
        except Exception as e:
            print(f"⚠️ Coverage analysis error: {str(e)}")
            return {"files": {}, "totals": {"percent_covered": 0}}
            
    def _generate_summary(self) -> Dict[str, Any]:
        """Generate test execution summary"""
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results.values() if r["status"] == "passed")
        failed_tests = sum(1 for r in self.test_results.values() if r["status"] == "failed")
        error_tests = sum(1 for r in self.test_results.values() if r["status"] == "error")
        
        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "error_tests": error_tests,
            "pass_percentage": (passed_tests / total_tests * 100) if total_tests > 0 else 0,
            "total_duration": sum(r["duration"] for r in self.test_results.values()),
            "total_queries": sum(r["query_count"] for r in self.test_results.values())
        }
        
    def _generate_performance_report(self) -> Dict[str, Any]:
        """Generate performance analysis report"""
        if not self.test_results:
            return {"average_duration": 0, "query_efficiency": 0, "slow_tests": []}
            
        durations = [r["duration"] for r in self.test_results.values()]
        query_counts = [r["query_count"] for r in self.test_results.values()]
        
        # Identify slow tests (top 10% by duration)
        test_durations = [(name, result["duration"]) for name, result in self.test_results.items()]
        test_durations.sort(key=lambda x: x[1], reverse=True)
        slow_tests = test_durations[:max(1, len(test_durations) // 10)]
        
        # Identify query-heavy tests
        test_queries = [(name, result["query_count"]) for name, result in self.test_results.items()]
        test_queries.sort(key=lambda x: x[1], reverse=True)
        query_heavy_tests = test_queries[:max(1, len(test_queries) // 10)]
        
        return {
            "average_duration": sum(durations) / len(durations),
            "max_duration": max(durations) if durations else 0,
            "average_queries": sum(query_counts) / len(query_counts) if query_counts else 0,
            "max_queries": max(query_counts) if query_counts else 0,
            "slow_tests": slow_tests,
            "query_heavy_tests": query_heavy_tests,
            "efficiency_score": self._calculate_efficiency_score()
        }
        
    def _generate_edge_case_report(self) -> Dict[str, Any]:
        """Generate edge case coverage report"""
        total_edge_cases = sum(data["total_cases"] for data in self.edge_case_tracking.values())
        
        # Calculate coverage percentages
        coverage_by_test = {}
        for test_name, data in self.edge_case_tracking.items():
            coverage_by_test[test_name] = {
                "covered": data["total_cases"],
                "percentage": 100 if data["total_cases"] > 0 else 0
            }
            
        return {
            "total_edge_cases_covered": total_edge_cases,
            "coverage_by_test": coverage_by_test,
            "edge_case_categories": self._categorize_edge_cases()
        }
        
    def _generate_trend_analysis(self) -> Dict[str, Any]:
        """Generate trend analysis from historical data"""
        # Load historical reports
        historical_data = self._load_historical_reports()
        
        if len(historical_data) < 2:
            return {"trend_data": "insufficient_data"}
            
        # Calculate trends
        latest = historical_data[-1]
        previous = historical_data[-2]
        
        coverage_trend = latest.get("coverage", {}).get("totals", {}).get("percent_covered", 0) - \
                        previous.get("coverage", {}).get("totals", {}).get("percent_covered", 0)
                        
        performance_trend = latest.get("performance", {}).get("average_duration", 0) - \
                           previous.get("performance", {}).get("average_duration", 0)
                           
        return {
            "coverage_trend": coverage_trend,
            "performance_trend": performance_trend,
            "test_count_trend": len(latest.get("test_results", {})) - len(previous.get("test_results", {})),
            "trend_direction": "improving" if coverage_trend > 0 and performance_trend < 0 else "declining"
        }
        
    def _calculate_efficiency_score(self) -> float:
        """Calculate overall test efficiency score (0-100)"""
        if not self.test_results:
            return 0
            
        # Factors: pass rate, speed, query efficiency
        summary = self._generate_summary()
        performance = self._generate_performance_report()
        
        pass_score = summary["pass_percentage"]
        speed_score = min(100, 100 - (performance["average_duration"] * 10))  # Penalize slow tests
        query_score = min(100, 100 - (performance["average_queries"] / 10))   # Penalize query-heavy tests
        
        return (pass_score * 0.5 + speed_score * 0.3 + query_score * 0.2)
        
    def _categorize_edge_cases(self) -> Dict[str, int]:
        """Categorize edge cases by type"""
        categories = {
            "validation": 0,
            "security": 0, 
            "performance": 0,
            "integration": 0,
            "business_logic": 0
        }
        
        for test_name, data in self.edge_case_tracking.items():
            # Categorize based on test name patterns
            if "validation" in test_name.lower():
                categories["validation"] += data["total_cases"]
            elif "security" in test_name.lower():
                categories["security"] += data["total_cases"]
            elif "performance" in test_name.lower():
                categories["performance"] += data["total_cases"]
            elif "integration" in test_name.lower():
                categories["integration"] += data["total_cases"]
            else:
                categories["business_logic"] += data["total_cases"]
                
        return categories
        
    def _load_historical_reports(self) -> List[Dict[str, Any]]:
        """Load historical coverage reports for trend analysis"""
        historical_reports = []
        
        # Look for reports from the last 30 days
        for i in range(30):
            date = datetime.now() - timedelta(days=i)
            filename = f"coverage_report_{date.strftime('%Y_%m_%d')}.json"
            filepath = self.output_dir / filename
            
            if filepath.exists():
                try:
                    with open(filepath) as f:
                        historical_reports.append(json.load(f))
                except Exception:
                    continue
                    
        return sorted(historical_reports, key=lambda x: x.get("timestamp", ""))
        
    def _update_performance_metrics(self, test_name: str, result: Dict[str, Any]):
        """Update performance metrics tracking"""
        if test_name not in self.performance_metrics:
            self.performance_metrics[test_name] = {
                "runs": 0,
                "total_duration": 0,
                "total_queries": 0,
                "avg_duration": 0,
                "avg_queries": 0
            }
            
        metrics = self.performance_metrics[test_name]
        metrics["runs"] += 1
        metrics["total_duration"] += result.get("duration", 0)
        metrics["total_queries"] += result.get("query_count", 0)
        metrics["avg_duration"] = metrics["total_duration"] / metrics["runs"]
        metrics["avg_queries"] = metrics["total_queries"] / metrics["runs"]
        
    def _generate_html_dashboard(self, report: Dict[str, Any]) -> str:
        """Generate comprehensive HTML dashboard"""
        html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verenigingen Test Coverage Dashboard</title>
    <style>
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0; 
            padding: 20px; 
            background: #f5f7fa;
            color: #333;
        }}
        .dashboard {{ 
            max-width: 1200px; 
            margin: 0 auto;
        }}
        .header {{ 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; 
            padding: 30px; 
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header h1 {{ 
            margin: 0 0 10px 0; 
            font-size: 2.5em;
        }}
        .header .subtitle {{ 
            opacity: 0.9; 
            font-size: 1.1em;
        }}
        .metrics-grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); 
            gap: 20px; 
            margin-bottom: 30px;
        }}
        .metric-card {{ 
            background: white; 
            padding: 25px; 
            border-radius: 10px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .metric-value {{ 
            font-size: 2.5em; 
            font-weight: bold; 
            margin: 10px 0;
        }}
        .metric-label {{ 
            color: #666; 
            text-transform: uppercase; 
            font-size: 0.9em; 
            letter-spacing: 1px;
        }}
        .success {{ color: #27ae60; }}
        .warning {{ color: #f39c12; }}
        .danger {{ color: #e74c3c; }}
        .info {{ color: #3498db; }}
        
        .section {{ 
            background: white; 
            margin-bottom: 30px; 
            border-radius: 10px; 
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section-header {{ 
            background: #34495e; 
            color: white; 
            padding: 20px; 
            font-size: 1.3em; 
            font-weight: bold;
        }}
        .section-content {{ 
            padding: 25px;
        }}
        
        .progress-bar {{ 
            background: #ecf0f1; 
            border-radius: 10px; 
            overflow: hidden; 
            height: 20px; 
            margin: 10px 0;
        }}
        .progress-fill {{ 
            height: 100%; 
            transition: width 0.3s ease;
        }}
        
        .test-list {{ 
            max-height: 400px; 
            overflow-y: auto;
        }}
        .test-item {{ 
            padding: 15px; 
            border-bottom: 1px solid #ecf0f1; 
            display: flex; 
            justify-content: space-between; 
            align-items: center;
        }}
        .test-item:last-child {{ 
            border-bottom: none;
        }}
        .test-status {{ 
            padding: 5px 12px; 
            border-radius: 20px; 
            font-size: 0.8em; 
            font-weight: bold; 
            text-transform: uppercase;
        }}
        .status-passed {{ 
            background: #d5f4e6; 
            color: #27ae60;
        }}
        .status-failed {{ 
            background: #fadbd8; 
            color: #e74c3c;
        }}
        .status-error {{ 
            background: #fdeaa7; 
            color: #f39c12;
        }}
        
        .chart-container {{ 
            height: 300px; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            background: #f8f9fa; 
            border-radius: 5px;
        }}
        
        .trend-indicator {{ 
            display: inline-flex; 
            align-items: center; 
            margin-left: 10px;
        }}
        .trend-up {{ color: #27ae60; }}
        .trend-down {{ color: #e74c3c; }}
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>🧪 Test Coverage Dashboard</h1>
            <div class="subtitle">Verenigingen Testing Infrastructure • Generated {timestamp}</div>
        </div>
        
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-value success">{coverage_percent:.1f}%</div>
                <div class="metric-label">Test Coverage</div>
                <div class="trend-indicator {coverage_trend_class}">
                    {coverage_trend_icon} {coverage_trend:.1f}%
                </div>
            </div>
            
            <div class="metric-card">
                <div class="metric-value {pass_rate_class}">{pass_rate:.1f}%</div>
                <div class="metric-label">Pass Rate</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-value info">{total_tests}</div>
                <div class="metric-label">Total Tests</div>
            </div>
            
            <div class="metric-card">
                <div class="metric-value {efficiency_class}">{efficiency_score:.0f}</div>
                <div class="metric-label">Efficiency Score</div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-header">📊 Test Results Overview</div>
            <div class="section-content">
                <div class="test-list">
                    {test_results_html}
                </div>
            </div>
        </div>
        
        <div class="section">
            <div class="section-header">⚡ Performance Metrics</div>
            <div class="section-content">
                <p><strong>Average Test Duration:</strong> {avg_duration:.2f}s</p>
                <p><strong>Average Database Queries:</strong> {avg_queries:.1f}</p>
                <p><strong>Slowest Tests:</strong></p>
                <ul>
                    {slow_tests_html}
                </ul>
            </div>
        </div>
        
        <div class="section">
            <div class="section-header">🎯 Edge Case Coverage</div>
            <div class="section-content">
                <p><strong>Total Edge Cases Covered:</strong> {total_edge_cases}</p>
                {edge_case_html}
            </div>
        </div>
        
        <div class="section">
            <div class="section-header">📈 Trends & Analysis</div>
            <div class="section-content">
                <p><strong>Trend Direction:</strong> {trend_direction}</p>
                <p><strong>Coverage Trend:</strong> {coverage_trend:+.1f}%</p>
                <p><strong>Performance Trend:</strong> {performance_trend:+.2f}s</p>
            </div>
        </div>
    </div>
</body>
</html>
        """
        
        # Extract data for template
        summary = report["summary"]
        performance = report["performance"]
        edge_cases = report["edge_cases"]
        trends = report["trends"]
        coverage = report["coverage"]
        
        # Generate test results HTML
        test_results_html = ""
        for test_name, result in report["test_results"].items():
            status_class = f"status-{result['status']}"
            test_results_html += f"""
                <div class="test-item">
                    <span>{test_name}</span>
                    <span class="test-status {status_class}">{result['status']}</span>
                </div>
            """
            
        # Generate slow tests HTML
        slow_tests_html = ""
        for test_name, duration in performance.get("slow_tests", [])[:5]:
            slow_tests_html += f"<li>{test_name}: {duration:.2f}s</li>"
            
        # Generate edge case HTML
        edge_case_html = ""
        for category, count in edge_cases.get("edge_case_categories", {}).items():
            edge_case_html += f"<p><strong>{category.title()}:</strong> {count} cases</p>"
            
        # Determine styling classes
        pass_rate = summary["pass_percentage"]
        pass_rate_class = "success" if pass_rate >= 90 else "warning" if pass_rate >= 70 else "danger"
        
        efficiency_score = performance.get("efficiency_score", 0)
        efficiency_class = "success" if efficiency_score >= 80 else "warning" if efficiency_score >= 60 else "danger"
        
        coverage_percent = coverage.get("totals", {}).get("percent_covered", 0)
        coverage_trend = trends.get("coverage_trend", 0)
        coverage_trend_class = "trend-up" if coverage_trend > 0 else "trend-down"
        coverage_trend_icon = "↗" if coverage_trend > 0 else "↘"
        
        # Render template
        html_content = html_template.format(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            coverage_percent=coverage_percent,
            pass_rate=pass_rate,
            total_tests=summary["total_tests"],
            efficiency_score=efficiency_score,
            pass_rate_class=pass_rate_class,
            efficiency_class=efficiency_class,
            coverage_trend_class=coverage_trend_class,
            coverage_trend_icon=coverage_trend_icon,
            coverage_trend=coverage_trend,
            test_results_html=test_results_html,
            avg_duration=performance.get("average_duration", 0),
            avg_queries=performance.get("average_queries", 0),
            slow_tests_html=slow_tests_html,
            total_edge_cases=edge_cases.get("total_edge_cases_covered", 0),
            edge_case_html=edge_case_html,
            trend_direction=trends.get("trend_direction", "stable").title(),
            performance_trend=trends.get("performance_trend", 0)
        )
        
        # Save HTML file
        html_path = self.output_dir / "coverage_dashboard.html"
        with open(html_path, "w") as f:
            f.write(html_content)
            
        return str(html_path)


@frappe.whitelist()
def generate_coverage_dashboard():
    """Generate test coverage dashboard - API endpoint for manual execution"""
    try:
        reporter = TestCoverageReporter()
        report = reporter.generate_coverage_report(include_html=True)
        
        return {
            "success": True,
            "message": "Coverage dashboard generated successfully",
            "dashboard_path": str(reporter.output_dir / "coverage_dashboard.html"),
            "json_path": str(reporter.output_dir / "coverage_report.json"),
            "summary": report["summary"]
        }
    except Exception as e:
        frappe.log_error(f"Coverage dashboard generation failed: {str(e)}")
        return {
            "success": False,
            "message": f"Failed to generate coverage dashboard: {str(e)}"
        }


@frappe.whitelist()
def get_coverage_summary():
    """Get quick coverage summary without full report generation"""
    try:
        reporter = TestCoverageReporter()
        
        # Quick summary without full analysis
        summary = {
            "timestamp": now(),
            "test_files_count": len(list(Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/tests").glob("test_*.py"))),
            "recent_results": reporter._load_historical_reports()[-1] if reporter._load_historical_reports() else None
        }
        
        return {
            "success": True,
            "summary": summary
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to get coverage summary: {str(e)}"
        }