#!/usr/bin/env python3
"""
Performance Baseline Tracker
Provides ongoing measurement and validation of improvement claims
"""

import time
import json
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Any

import frappe
from frappe.utils import nowdate, now


class PerformanceBaselineTracker:
    """Track performance baselines and validate improvement claims"""
    
    def __init__(self):
        self.baseline_file = "/home/frappe/frappe-bench/apps/verenigingen/performance_baselines.json"
        self.load_baselines()
    
    def load_baselines(self):
        """Load existing baselines or create new ones"""
        try:
            with open(self.baseline_file, 'r') as f:
                self.baselines = json.load(f)
        except FileNotFoundError:
            self.baselines = {
                "created_date": nowdate(),
                "measurements": {},
                "improvement_targets": {},
                "validation_history": []
            }
    
    def save_baselines(self):
        """Save baselines to file"""
        try:
            with open(self.baseline_file, 'w') as f:
                json.dump(self.baselines, f, indent=2, default=str)
        except Exception as e:
            frappe.log_error(f"Failed to save baselines: {e}")
    
    @frappe.whitelist()
    def establish_baseline(self, measurement_type: str = "all") -> Dict:
        """Establish performance baselines for comparison"""
        from verenigingen.api.performance_measurement import (
            measure_payment_history_performance,
            count_payment_mixin_complexity,
            measure_database_query_patterns
        )
        
        results = {
            "baseline_date": now(),
            "measurement_type": measurement_type,
            "measurements": {}
        }
        
        try:
            if measurement_type in ["all", "payment_history"]:
                # Payment history baseline
                ph_result = measure_payment_history_performance(10)
                if "summary" in ph_result:
                    results["measurements"]["payment_history"] = {
                        "avg_execution_time": ph_result["summary"]["avg_execution_time"],
                        "avg_query_count": ph_result["summary"]["avg_query_count"],
                        "success_rate": ph_result["summary"]["success_rate"],
                        "sample_size": ph_result["summary"]["total_tests"]
                    }
            
            if measurement_type in ["all", "code_complexity"]:
                # Code complexity baseline
                complexity_result = count_payment_mixin_complexity()
                if "total_lines" in complexity_result:
                    results["measurements"]["code_complexity"] = {
                        "total_lines": complexity_result["total_lines"],
                        "code_lines": complexity_result["code_lines"],
                        "method_count": complexity_result["method_count"],
                        "avg_method_size": complexity_result["avg_method_size"],
                        "largest_method": complexity_result.get("largest_method", {})
                    }
            
            if measurement_type in ["all", "query_patterns"]:
                # Query patterns baseline
                query_result = measure_database_query_patterns()
                if "query_analysis" in query_result:
                    successful_ops = [op for op in query_result["query_analysis"] if op.get("success")]
                    if successful_ops:
                        results["measurements"]["query_patterns"] = {
                            "avg_queries_per_operation": statistics.mean([op["query_count"] for op in successful_ops]),
                            "avg_execution_time": statistics.mean([op["execution_time"] for op in successful_ops]),
                            "operations_tested": len(successful_ops)
                        }
            
            # Save to baselines
            baseline_key = f"baseline_{nowdate()}"
            self.baselines["measurements"][baseline_key] = results
            self.save_baselines()
            
            return results
            
        except Exception as e:
            frappe.log_error(f"Error establishing baseline: {e}")
            return {"error": str(e)}
    
    @frappe.whitelist()
    def validate_improvement_claim(self, claim_type: str, claimed_improvement: float, actual_measurement: Dict) -> Dict:
        """
        Validate improvement claims against actual measurements
        
        Args:
            claim_type: Type of improvement (payment_history, query_reduction, code_complexity)
            claimed_improvement: Claimed improvement percentage (e.g., 67 for 67%)
            actual_measurement: Current measurement data
            
        Returns:
            Validation result with evidence
        """
        try:
            # Get latest baseline
            latest_baseline = self.get_latest_baseline()
            if not latest_baseline or claim_type not in latest_baseline.get("measurements", {}):
                return {
                    "valid": False,
                    "error": f"No baseline found for {claim_type}",
                    "recommendation": "Establish baseline first"
                }
            
            baseline_data = latest_baseline["measurements"][claim_type]
            
            validation_result = {
                "claim_type": claim_type,
                "claimed_improvement": claimed_improvement,
                "validation_date": now(),
                "baseline_data": baseline_data,
                "actual_measurement": actual_measurement,
                "valid": False,
                "evidence": {},
                "recommendation": ""
            }
            
            # Validate based on claim type
            if claim_type == "payment_history":
                baseline_time = baseline_data.get("avg_execution_time", 0)
                current_time = actual_measurement.get("avg_execution_time", 0)
                
                if baseline_time > 0:
                    actual_improvement = ((baseline_time - current_time) / baseline_time) * 100
                    validation_result["evidence"] = {
                        "baseline_time": baseline_time,
                        "current_time": current_time,
                        "actual_improvement": actual_improvement,
                        "improvement_ratio": current_time / baseline_time if baseline_time > 0 else 0
                    }
                    
                    # Check if claim is realistic (within 20% of actual)
                    validation_result["valid"] = abs(actual_improvement - claimed_improvement) <= 20
                    
                    if not validation_result["valid"]:
                        validation_result["recommendation"] = f"Claimed {claimed_improvement}% improvement, but actual is {actual_improvement:.1f}%. Adjust expectations."
            
            elif claim_type == "query_reduction":
                baseline_queries = baseline_data.get("avg_queries_per_operation", 0)
                current_queries = actual_measurement.get("avg_queries_per_operation", 0)
                
                if baseline_queries > 0:
                    actual_reduction = ((baseline_queries - current_queries) / baseline_queries) * 100
                    validation_result["evidence"] = {
                        "baseline_queries": baseline_queries,
                        "current_queries": current_queries,
                        "actual_reduction": actual_reduction,
                        "reduction_ratio": current_queries / baseline_queries if baseline_queries > 0 else 0
                    }
                    
                    validation_result["valid"] = abs(actual_reduction - claimed_improvement) <= 15
                    
                    if not validation_result["valid"]:
                        validation_result["recommendation"] = f"Claimed {claimed_improvement}% reduction, but actual is {actual_reduction:.1f}%. Query optimization may be less effective than expected."
            
            elif claim_type == "code_complexity":
                baseline_lines = baseline_data.get("total_lines", 0)
                current_lines = actual_measurement.get("total_lines", 0)
                
                if baseline_lines > 0:
                    actual_reduction = ((baseline_lines - current_lines) / baseline_lines) * 100
                    validation_result["evidence"] = {
                        "baseline_lines": baseline_lines,
                        "current_lines": current_lines,
                        "actual_reduction": actual_reduction,
                        "reduction_ratio": current_lines / baseline_lines if baseline_lines > 0 else 0
                    }
                    
                    validation_result["valid"] = abs(actual_reduction - claimed_improvement) <= 25
                    
                    if not validation_result["valid"]:
                        validation_result["recommendation"] = f"Claimed {claimed_improvement}% reduction, but actual is {actual_reduction:.1f}%. Code refactoring goals may be too aggressive."
            
            # Record validation
            self.baselines["validation_history"].append(validation_result)
            self.save_baselines()
            
            return validation_result
            
        except Exception as e:
            frappe.log_error(f"Error validating improvement claim: {e}")
            return {"error": str(e), "valid": False}
    
    def get_latest_baseline(self) -> Dict:
        """Get the most recent baseline measurement"""
        if not self.baselines.get("measurements"):
            return None
        
        # Sort by date and get latest
        baseline_keys = sorted(self.baselines["measurements"].keys(), reverse=True)
        if baseline_keys:
            return self.baselines["measurements"][baseline_keys[0]]
        return None
    
    @frappe.whitelist()
    def generate_improvement_report(self) -> Dict:
        """Generate comprehensive improvement validation report"""
        try:
            report = {
                "report_date": now(),
                "baseline_summary": {},
                "validation_summary": {},
                "recommendations": []
            }
            
            # Summarize baselines
            latest_baseline = self.get_latest_baseline()
            if latest_baseline:
                report["baseline_summary"] = {
                    "baseline_date": latest_baseline.get("baseline_date"),
                    "measurements_available": list(latest_baseline.get("measurements", {}).keys()),
                    "key_metrics": {}
                }
                
                # Extract key metrics
                if "payment_history" in latest_baseline.get("measurements", {}):
                    ph_data = latest_baseline["measurements"]["payment_history"]
                    report["baseline_summary"]["key_metrics"]["payment_history"] = f"{ph_data.get('avg_execution_time', 0):.3f}s avg, {ph_data.get('avg_query_count', 0):.1f} queries"
                
                if "code_complexity" in latest_baseline.get("measurements", {}):
                    cc_data = latest_baseline["measurements"]["code_complexity"]
                    report["baseline_summary"]["key_metrics"]["code_complexity"] = f"{cc_data.get('total_lines', 0)} lines, {cc_data.get('method_count', 0)} methods"
            
            # Summarize validations
            validations = self.baselines.get("validation_history", [])
            if validations:
                recent_validations = validations[-10:]  # Last 10 validations
                valid_count = sum(1 for v in recent_validations if v.get("valid"))
                
                report["validation_summary"] = {
                    "total_validations": len(validations),
                    "recent_valid_rate": (valid_count / len(recent_validations)) * 100 if recent_validations else 0,
                    "common_issues": self._analyze_validation_patterns(recent_validations)
                }
            
            # Generate recommendations
            report["recommendations"] = self._generate_recommendations(latest_baseline, validations)
            
            return report
            
        except Exception as e:
            frappe.log_error(f"Error generating improvement report: {e}")
            return {"error": str(e)}
    
    def _analyze_validation_patterns(self, validations: List[Dict]) -> List[str]:
        """Analyze patterns in validation failures"""
        issues = []
        
        failed_validations = [v for v in validations if not v.get("valid")]
        if len(failed_validations) > len(validations) * 0.5:
            issues.append("Over 50% of improvement claims fail validation")
        
        claim_types = {}
        for v in failed_validations:
            claim_type = v.get("claim_type", "unknown")
            claim_types[claim_type] = claim_types.get(claim_type, 0) + 1
        
        for claim_type, count in claim_types.items():
            if count >= 2:
                issues.append(f"Repeated validation failures for {claim_type} claims")
        
        return issues
    
    def _generate_recommendations(self, baseline: Dict, validations: List[Dict]) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        if not baseline:
            recommendations.append("Establish performance baselines before making improvement claims")
            return recommendations
        
        # Analyze baseline performance
        if "payment_history" in baseline.get("measurements", {}):
            ph_data = baseline["measurements"]["payment_history"]
            avg_time = ph_data.get("avg_execution_time", 0)
            
            if avg_time < 0.2:  # Already fast
                recommendations.append("Payment history is already fast (<200ms). Focus optimization efforts elsewhere.")
            elif avg_time > 1.0:  # Actually slow
                recommendations.append("Payment history optimization could provide significant user benefit.")
        
        # Analyze validation history
        if validations:
            recent_failed = [v for v in validations[-5:] if not v.get("valid")]
            if len(recent_failed) >= 3:
                recommendations.append("Multiple recent improvement claims have failed validation. Review claim methodology.")
        
        return recommendations


@frappe.whitelist()
def quick_performance_check() -> Dict:
    """Quick performance check for ongoing monitoring"""
    tracker = PerformanceBaselineTracker()
    
    # Quick measurement
    from verenigingen.api.performance_measurement import measure_payment_history_performance
    
    start_time = time.time()
    result = measure_payment_history_performance(3)  # Quick test with 3 members
    total_time = time.time() - start_time
    
    if "summary" in result:
        return {
            "status": "healthy" if result["summary"]["avg_execution_time"] < 0.5 else "slow",
            "avg_execution_time": result["summary"]["avg_execution_time"],
            "avg_query_count": result["summary"]["avg_query_count"],
            "measurement_overhead": total_time,
            "timestamp": now()
        }
    else:
        return {"status": "error", "error": result.get("error", "Unknown error")}


if __name__ == "__main__":
    # Can be run directly for monitoring
    tracker = PerformanceBaselineTracker()
    baseline = tracker.establish_baseline()
    print("Baseline established:", baseline)