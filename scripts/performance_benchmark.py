#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Benchmarking Tool
Establishes and tracks performance baselines for the Verenigingen app
"""

import time
import json
import statistics
import frappe
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd


class PerformanceBenchmark:
    """Performance benchmarking for Verenigingen app"""
    
    def __init__(self):
        self.results = {}
        self.baseline_file = "performance_baseline.json"
        self.history_file = "performance_history.json"
        
    def time_function(self, func, *args, iterations=10, **kwargs):
        """Time a function execution"""
        times = []
        
        for _ in range(iterations):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            end = time.perf_counter()
            times.append(end - start)
            
        return {
            "min": min(times),
            "max": max(times),
            "mean": statistics.mean(times),
            "median": statistics.median(times),
            "stdev": statistics.stdev(times) if len(times) > 1 else 0,
            "iterations": iterations
        }
        
    def benchmark_member_operations(self):
        """Benchmark member-related operations"""
        print("📊 Benchmarking member operations...")
        
        # Member list query
        def get_member_list(limit=100):
            return frappe.get_all("Member", 
                                fields=["name", "full_name", "status"],
                                limit=limit)
        
        # Member detail fetch
        def get_member_details(member_name):
            return frappe.get_doc("Member", member_name)
            
        # Benchmark different list sizes
        list_sizes = [10, 50, 100, 500, 1000]
        list_results = {}
        
        for size in list_sizes:
            print(f"  Testing list size: {size}")
            list_results[f"list_{size}"] = self.time_function(
                get_member_list, 
                limit=size,
                iterations=5
            )
            
        self.results["member_list_operations"] = list_results
        
        # Benchmark single member fetch
        members = frappe.get_all("Member", limit=1)
        if members:
            self.results["member_detail_fetch"] = self.time_function(
                get_member_details,
                members[0].name,
                iterations=20
            )
            
    def benchmark_volunteer_operations(self):
        """Benchmark volunteer-related operations"""
        print("📊 Benchmarking volunteer operations...")
        
        # Complex volunteer query with joins
        def get_volunteer_assignments():
            return frappe.db.sql("""
                SELECT 
                    v.name, v.volunteer_name,
                    COUNT(va.name) as assignment_count,
                    SUM(ve.amount) as total_expenses
                FROM `tabVolunteer` v
                LEFT JOIN `tabVolunteer Assignment` va ON va.volunteer = v.name
                LEFT JOIN `tabVolunteer Expense` ve ON ve.volunteer = v.name
                GROUP BY v.name
                LIMIT 100
            """, as_dict=True)
            
        self.results["volunteer_complex_query"] = self.time_function(
            get_volunteer_assignments,
            iterations=10
        )
        
    def benchmark_financial_operations(self):
        """Benchmark financial operations"""
        print("📊 Benchmarking financial operations...")
        
        # Invoice creation simulation
        def create_test_invoice():
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = frappe.db.get_value("Customer", {}, "name")
            invoice.company = frappe.defaults.get_defaults().company
            invoice.posting_date = frappe.utils.today()
            invoice.append("items", {
                "item_code": frappe.db.get_value("Item", {"item_group": ["!=", ""]}, "name"),
                "qty": 1,
                "rate": 100
            })
            # Don't actually save, just validate
            invoice.validate()
            return invoice
            
        if frappe.db.exists("Customer", {}):
            self.results["invoice_creation"] = self.time_function(
                create_test_invoice,
                iterations=5
            )
            
    def benchmark_report_generation(self):
        """Benchmark report generation"""
        print("📊 Benchmarking report generation...")
        
        # Member summary report
        def generate_member_report():
            return frappe.db.sql("""
                SELECT 
                    status, 
                    COUNT(*) as count,
                    COUNT(DISTINCT chapter) as chapter_count
                FROM `tabMember`
                GROUP BY status
            """, as_dict=True)
            
        self.results["member_summary_report"] = self.time_function(
            generate_member_report,
            iterations=10
        )
        
    def benchmark_api_endpoints(self):
        """Benchmark API endpoint performance"""
        print("📊 Benchmarking API endpoints...")
        
        # Simulate API calls
        api_endpoints = [
            {
                "name": "get_dashboard_data",
                "method": "verenigingen.api.chapter_dashboard.get_dashboard_data",
                "args": {}
            },
            {
                "name": "get_member_list",
                "method": "verenigingen.api.member.get_member_list",
                "args": {"filters": {}, "limit": 50}
            }
        ]
        
        for endpoint in api_endpoints:
            if frappe.db.exists("DocType", "Member"):  # Ensure data exists
                try:
                    def call_api():
                        return frappe.call(
                            endpoint["method"],
                            **endpoint["args"]
                        )
                        
                    self.results[f"api_{endpoint['name']}"] = self.time_function(
                        call_api,
                        iterations=5
                    )
                except Exception as e:
                    print(f"  ⚠️  Error benchmarking {endpoint['name']}: {e}")
                    
    def compare_with_baseline(self):
        """Compare current results with baseline"""
        if not Path(self.baseline_file).exists():
            print("⚠️  No baseline found. Current results will become the baseline.")
            self.save_baseline()
            return {}
            
        with open(self.baseline_file, 'r') as f:
            baseline = json.load(f)
            
        comparison = {}
        
        for operation, metrics in self.results.items():
            if operation in baseline:
                if isinstance(metrics, dict) and "mean" in metrics:
                    baseline_mean = baseline[operation].get("mean", 0)
                    current_mean = metrics["mean"]
                    
                    if baseline_mean > 0:
                        change_percent = ((current_mean - baseline_mean) / baseline_mean) * 100
                        comparison[operation] = {
                            "baseline": baseline_mean,
                            "current": current_mean,
                            "change_percent": change_percent,
                            "status": "🟢" if change_percent <= 10 else "🟡" if change_percent <= 25 else "🔴"
                        }
                        
        return comparison
        
    def save_baseline(self):
        """Save current results as baseline"""
        with open(self.baseline_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"✅ Baseline saved to {self.baseline_file}")
        
    def save_history(self):
        """Save results to history"""
        history = []
        
        if Path(self.history_file).exists():
            with open(self.history_file, 'r') as f:
                history = json.load(f)
                
        history.append({
            "timestamp": datetime.now().isoformat(),
            "results": self.results
        })
        
        # Keep last 100 entries
        history = history[-100:]
        
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=2)
            
    def generate_report(self):
        """Generate performance report"""
        print("\n📈 Performance Benchmark Report")
        print("=" * 50)
        
        # Display results
        for operation, metrics in self.results.items():
            print(f"\n{operation}:")
            if isinstance(metrics, dict):
                if "mean" in metrics:
                    print(f"  Mean: {metrics['mean']*1000:.2f}ms")
                    print(f"  Min: {metrics['min']*1000:.2f}ms")
                    print(f"  Max: {metrics['max']*1000:.2f}ms")
                    print(f"  Stdev: {metrics['stdev']*1000:.2f}ms")
                else:
                    # Nested results (like list operations)
                    for sub_op, sub_metrics in metrics.items():
                        print(f"  {sub_op}:")
                        print(f"    Mean: {sub_metrics['mean']*1000:.2f}ms")
                        
        # Compare with baseline
        print("\n📊 Baseline Comparison")
        print("-" * 50)
        
        comparison = self.compare_with_baseline()
        
        if comparison:
            for operation, comp in comparison.items():
                print(f"{comp['status']} {operation}:")
                print(f"  Baseline: {comp['baseline']*1000:.2f}ms")
                print(f"  Current: {comp['current']*1000:.2f}ms")
                print(f"  Change: {comp['change_percent']:+.1f}%")
        else:
            print("No baseline comparison available.")
            
    def plot_trends(self):
        """Plot performance trends"""
        if not Path(self.history_file).exists():
            print("⚠️  No history data available for plotting.")
            return
            
        with open(self.history_file, 'r') as f:
            history = json.load(f)
            
        if len(history) < 2:
            print("⚠️  Not enough history data for plotting.")
            return
            
        # Extract data for plotting
        timestamps = [entry["timestamp"] for entry in history]
        
        # Plot member list operations
        plt.figure(figsize=(12, 6))
        
        # Extract specific metric trends
        operations = ["member_detail_fetch", "volunteer_complex_query", "member_summary_report"]
        
        for op in operations:
            values = []
            for entry in history:
                if op in entry["results"] and "mean" in entry["results"][op]:
                    values.append(entry["results"][op]["mean"] * 1000)  # Convert to ms
                else:
                    values.append(None)
                    
            if any(v is not None for v in values):
                plt.plot(timestamps, values, marker='o', label=op)
                
        plt.xlabel("Timestamp")
        plt.ylabel("Response Time (ms)")
        plt.title("Performance Trends")
        plt.legend()
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Save plot
        plt.savefig("performance_trends.png")
        print("✅ Performance trends plot saved to performance_trends.png")
        
    def run_full_benchmark(self):
        """Run complete benchmark suite"""
        print("🚀 Starting performance benchmark for Verenigingen app...\n")
        
        # Run all benchmarks
        self.benchmark_member_operations()
        self.benchmark_volunteer_operations()
        self.benchmark_financial_operations()
        self.benchmark_report_generation()
        self.benchmark_api_endpoints()
        
        # Generate report
        self.generate_report()
        
        # Save results
        self.save_history()
        
        # Plot trends if available
        self.plot_trends()
        
        print("\n✅ Performance benchmark complete!")
        
        # Return overall performance score
        total_operations = 0
        total_time = 0
        
        for operation, metrics in self.results.items():
            if isinstance(metrics, dict) and "mean" in metrics:
                total_operations += 1
                total_time += metrics["mean"]
                
        avg_time = total_time / total_operations if total_operations > 0 else 0
        
        # Score based on average response time
        if avg_time < 0.1:  # < 100ms
            score = "Excellent"
        elif avg_time < 0.5:  # < 500ms
            score = "Good"
        elif avg_time < 1.0:  # < 1s
            score = "Fair"
        else:
            score = "Needs Improvement"
            
        print(f"\n🏆 Overall Performance Score: {score}")
        print(f"   Average operation time: {avg_time*1000:.2f}ms")
        
        return score


if __name__ == "__main__":
    # Initialize Frappe
    import sys
    sys.path.append('/home/frappe/frappe-bench/sites')
    
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
    
    try:
        benchmark = PerformanceBenchmark()
        benchmark.run_full_benchmark()
    finally:
        frappe.destroy()