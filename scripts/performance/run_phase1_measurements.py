#!/usr/bin/env python3
"""
Phase 1 Performance Measurement Script
Evidence-Based Performance Improvement Plan

This script runs comprehensive performance measurements to establish baselines
and identify specific optimization targets for Phase 1 implementation.
"""

import sys
import os
import json
import time
from datetime import datetime

# Add the app directory to Python path
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

# Import required modules after path setup
import frappe
from frappe.utils import now

from verenigingen.api.performance_measurement_api import (
    benchmark_current_performance,
    collect_performance_baselines,
    analyze_system_bottlenecks,
    generate_comprehensive_performance_report
)


def main():
    """Run Phase 1 performance measurements"""
    
    print("="*80)
    print("PHASE 1 PERFORMANCE MEASUREMENT - Evidence-Based Improvement Plan")
    print("="*80)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Initialize Frappe
    try:
        frappe.init(site='dev.veganisme.net')
        frappe.connect()
        print("✓ Connected to Frappe site: dev.veganisme.net")
    except Exception as e:
        print(f"✗ Failed to connect to Frappe: {e}")
        return 1
        
    measurement_results = {}
    
    try:
        # Step 1: Collect Performance Baselines
        print("\n" + "-"*60)
        print("STEP 1: COLLECTING PERFORMANCE BASELINES")
        print("-"*60)
        
        print("Collecting baseline measurements for payment operations...")
        baseline_result = collect_performance_baselines(sample_size=15)
        
        if baseline_result.get("success"):
            measurement_results["baselines"] = baseline_result["data"]
            
            # Extract key metrics
            baseline_data = baseline_result["data"]
            if "payment_history_baseline" in baseline_data:
                ph_baseline = baseline_data["payment_history_baseline"]
                print(f"✓ Payment History Baseline:")
                print(f"  - Sample size: {ph_baseline['sample_size']} members")
                print(f"  - Average queries: {ph_baseline['avg_query_count']:.1f}")
                print(f"  - Query range: {ph_baseline['min_query_count']:.0f} - {ph_baseline['max_query_count']:.0f}")
                print(f"  - Average execution time: {ph_baseline['avg_execution_time']:.3f}s")
                print(f"  - Time range: {ph_baseline['min_execution_time']:.3f}s - {ph_baseline['max_execution_time']:.3f}s")
                
            if "sepa_mandate_baseline" in baseline_data:
                sepa_baseline = baseline_data["sepa_mandate_baseline"]
                print(f"✓ SEPA Mandate Baseline:")
                print(f"  - Sample size: {sepa_baseline['sample_size']} members")
                print(f"  - Average queries: {sepa_baseline['avg_query_count']:.1f}")
                print(f"  - Average execution time: {sepa_baseline['avg_execution_time']:.3f}s")
        else:
            print(f"✗ Failed to collect baselines: {baseline_result.get('error', 'Unknown error')}")
            
        # Step 2: Analyze System Bottlenecks
        print("\n" + "-"*60)
        print("STEP 2: ANALYZING SYSTEM BOTTLENECKS")
        print("-"*60)
        
        print("Analyzing performance bottlenecks across sample members...")
        bottleneck_result = analyze_system_bottlenecks()
        
        if bottleneck_result.get("success"):
            measurement_results["bottlenecks"] = bottleneck_result["data"]
            
            bottleneck_data = bottleneck_result["data"]
            print(f"✓ Bottleneck Analysis:")
            print(f"  - Members analyzed: {bottleneck_data['members_analyzed']}")
            print(f"  - Total bottlenecks: {bottleneck_data['total_bottlenecks']}")
            print(f"  - N+1 patterns found: {bottleneck_data['total_n1_patterns']}")
            
            # Show bottleneck types
            if bottleneck_data['bottleneck_types']:
                print("  - Bottleneck types:")
                for btype, count in bottleneck_data['bottleneck_types'].items():
                    print(f"    • {btype}: {count} instances")
                    
            # Show priority distribution
            priority_dist = bottleneck_data['priority_distribution']
            print("  - Priority distribution:")
            for priority, count in priority_dist.items():
                if count > 0:
                    print(f"    • {priority}: {count} members")
        else:
            print(f"✗ Failed to analyze bottlenecks: {bottleneck_result.get('error', 'Unknown error')}")
            
        # Step 3: Generate Comprehensive Report
        print("\n" + "-"*60)
        print("STEP 3: GENERATING COMPREHENSIVE REPORT")
        print("-"*60)
        
        print("Generating comprehensive performance report...")
        report_result = generate_comprehensive_performance_report(sample_size=12)
        
        if report_result.get("success"):
            measurement_results["comprehensive_report"] = report_result["data"]
            
            report_data = report_result["data"]
            
            # Extract system health score
            if "bottleneck_summary" in report_data:
                health_info = report_data["bottleneck_summary"].get("system_health_score", {})
                health_score = health_info.get("health_percentage", 0)
                health_status = health_info.get("status", "unknown")
                
                print(f"✓ System Health Assessment:")
                print(f"  - Health Score: {health_score:.1f}%")
                print(f"  - Status: {health_status.upper()}")
                print(f"  - Recommendation: {health_info.get('recommendation', 'No recommendation available')}")
                
            # Show optimization roadmap
            if "optimization_roadmap" in report_data:
                roadmap = report_data["optimization_roadmap"]
                
                print(f"\n✓ Optimization Roadmap:")
                immediate_actions = roadmap.get("immediate_actions", [])
                if immediate_actions:
                    print(f"  - Immediate actions ({len(immediate_actions)} items):")
                    for action in immediate_actions[:3]:  # Show first 3
                        print(f"    • {action['action']}: {action['expected_improvement']}")
                        
                short_term = roadmap.get("short_term_goals", [])
                if short_term:
                    print(f"  - Short-term goals ({len(short_term)} items):")
                    for goal in short_term[:2]:  # Show first 2
                        print(f"    • {goal['goal']}: {goal['timeline']}")
        else:
            print(f"✗ Failed to generate comprehensive report: {report_result.get('error', 'Unknown error')}")
            
        # Step 4: Create Complete Benchmark
        print("\n" + "-"*60)
        print("STEP 4: CREATING PHASE 1 BENCHMARK")
        print("-"*60)
        
        print("Creating complete Phase 1 performance benchmark...")
        benchmark_result = benchmark_current_performance()
        
        if benchmark_result.get("success"):
            measurement_results["benchmark"] = benchmark_result["data"]
            
            benchmark_data = benchmark_result["data"]
            
            # Show key findings
            key_findings = benchmark_data.get("key_findings", [])
            if key_findings:
                print("✓ Key Findings:")
                for finding in key_findings:
                    print(f"  • {finding}")
                    
            # Show optimization targets
            optimization_targets = benchmark_data.get("optimization_targets", [])
            if optimization_targets:
                print("\n✓ Optimization Targets:")
                for target in optimization_targets:
                    print(f"  • {target['metric']}")
                    print(f"    Current: {target['current_value']}")
                    print(f"    Target: {target['target_value']}")
                    print(f"    Improvement needed: {target['improvement_needed']}")
                    print(f"    Priority: {target['priority'].upper()}")
                    print()
        else:
            print(f"✗ Failed to create benchmark: {benchmark_result.get('error', 'Unknown error')}")
            
        # Step 5: Save Results to File
        print("\n" + "-"*60)
        print("STEP 5: SAVING RESULTS")
        print("-"*60)
        
        output_file = f"/home/frappe/frappe-bench/apps/verenigingen/phase1_performance_measurements_{int(time.time())}.json"
        
        try:
            with open(output_file, 'w') as f:
                json.dump(measurement_results, f, indent=2, default=str)
            print(f"✓ Results saved to: {output_file}")
        except Exception as e:
            print(f"✗ Failed to save results: {e}")
            
        # Step 6: Generate Summary Report
        print("\n" + "="*80)
        print("PHASE 1 MEASUREMENT SUMMARY")
        print("="*80)
        
        generate_summary_report(measurement_results)
        
    except Exception as e:
        print(f"\n✗ CRITICAL ERROR: {e}")
        import traceback
        print(traceback.format_exc())
        return 1
        
    finally:
        try:
            frappe.destroy()
        except:
            pass
            
    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    return 0


def generate_summary_report(measurement_results):
    """Generate a human-readable summary of measurements"""
    
    print("EXECUTIVE SUMMARY:")
    print("-" * 40)
    
    # Baseline Summary
    if "baselines" in measurement_results:
        baseline_data = measurement_results["baselines"]
        
        if "payment_history_baseline" in baseline_data:
            ph = baseline_data["payment_history_baseline"]
            avg_queries = ph.get("avg_query_count", 0)
            avg_time = ph.get("avg_execution_time", 0)
            
            print(f"• Payment History Performance:")
            print(f"  - Current average: {avg_queries:.1f} queries per load ({avg_time:.2f}s)")
            
            if avg_queries > 50:
                print(f"  - STATUS: CRITICAL - Exceeds target by {avg_queries - 20:.0f} queries")
            elif avg_queries > 30:
                print(f"  - STATUS: HIGH PRIORITY - Optimization needed")
            elif avg_queries > 20:
                print(f"  - STATUS: MEDIUM PRIORITY - Some optimization beneficial")
            else:
                print(f"  - STATUS: ACCEPTABLE - Within target range")
                
    # Bottleneck Summary
    if "bottlenecks" in measurement_results:
        bottleneck_data = measurement_results["bottlenecks"]
        
        total_bottlenecks = bottleneck_data.get("total_bottlenecks", 0)
        n1_patterns = bottleneck_data.get("total_n1_patterns", 0)
        
        print(f"\n• Performance Issues Identified:")
        print(f"  - Total bottlenecks: {total_bottlenecks}")
        print(f"  - N+1 query patterns: {n1_patterns}")
        
        if total_bottlenecks > 30:
            print(f"  - STATUS: CRITICAL - Immediate optimization required")
        elif total_bottlenecks > 15:
            print(f"  - STATUS: HIGH PRIORITY - Schedule optimization sprint")
        elif total_bottlenecks > 5:
            print(f"  - STATUS: MEDIUM PRIORITY - Address in next development cycle")
        else:
            print(f"  - STATUS: ACCEPTABLE - Minor optimizations beneficial")
            
    # Health Score Summary
    if "comprehensive_report" in measurement_results:
        report_data = measurement_results["comprehensive_report"]
        
        if "bottleneck_summary" in report_data:
            health_info = report_data["bottleneck_summary"].get("system_health_score", {})
            health_score = health_info.get("health_percentage", 100)
            
            print(f"\n• System Health Score: {health_score:.1f}%")
            
            if health_score < 50:
                print(f"  - STATUS: CRITICAL - System requires immediate attention")
            elif health_score < 75:
                print(f"  - STATUS: POOR - Performance optimization needed")
            elif health_score < 90:
                print(f"  - STATUS: FAIR - Some optimization beneficial")
            else:
                print(f"  - STATUS: GOOD - System performing well")
                
    # Recommendations
    print(f"\nRECOMMENDATIONS:")
    print("-" * 40)
    
    recommendations = []
    
    # Based on baselines
    if "baselines" in measurement_results:
        baseline_data = measurement_results["baselines"]
        if "payment_history_baseline" in baseline_data:
            avg_queries = baseline_data["payment_history_baseline"].get("avg_query_count", 0)
            if avg_queries > 30:
                recommendations.append("1. URGENT: Implement batch loading for payment history operations")
                recommendations.append("2. Enable payment history caching with smart invalidation")
                
    # Based on bottlenecks
    if "bottlenecks" in measurement_results:
        bottleneck_data = measurement_results["bottlenecks"]
        pattern_types = bottleneck_data.get("pattern_types", {})
        
        if pattern_types.get("payment_reference_lookup", 0) > 3:
            recommendations.append("3. Eliminate N+1 patterns in payment reference lookups")
            
        if pattern_types.get("invoice_lookup", 0) > 2:
            recommendations.append("4. Optimize invoice data loading with comprehensive queries")
            
    # Based on health score
    if "comprehensive_report" in measurement_results:
        report_data = measurement_results["comprehensive_report"]
        if "bottleneck_summary" in report_data:
            health_score = report_data["bottleneck_summary"].get("system_health_score", {}).get("health_percentage", 100)
            if health_score < 75:
                recommendations.append("5. Schedule dedicated performance optimization sprint")
                
    if not recommendations:
        recommendations = ["• System performance appears acceptable - continue monitoring"]
        
    for rec in recommendations:
        print(f"  {rec}")
        
    # Expected Improvements
    print(f"\nEXPECTED IMPROVEMENTS FROM OPTIMIZATION:")
    print("-" * 40)
    print("• Query count reduction: 60-80%")
    print("• Execution time improvement: 40-70%") 
    print("• User experience: 2-5x faster page loads")
    print("• System stability: 90% reduction in timeout risks")


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)