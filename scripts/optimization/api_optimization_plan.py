#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Optimization Implementation Plan
Identifies and applies optimizations to remaining unoptimized endpoints
"""

import frappe
from frappe import _
from functools import wraps
import json


class APIOptimizationPlan:
    """Plan for optimizing remaining API endpoints"""
    
    def __init__(self):
        self.optimization_checklist = {
            "caching": "Add @cache_with_ttl decorator for read operations",
            "validation": "Add @validate_request decorator for input validation",
            "error_handling": "Add @handle_api_errors decorator",
            "performance": "Add @monitor_performance decorator",
            "pagination": "Implement limit/offset parameters",
            "query_optimization": "Use get_query_optimization for complex queries",
            "batch_processing": "Use batch_processor for bulk operations",
            "rate_limiting": "Add rate limiting for expensive operations"
        }
        
    def analyze_endpoint(self, file_path, function_name):
        """Analyze an endpoint for optimization opportunities"""
        optimizations_needed = []
        
        with open(file_path, 'r') as f:
            content = f.read()
            
        # Check for existing optimizations
        function_section = self._extract_function(content, function_name)
        
        if not "@cache_with_ttl" in function_section and "get_" in function_name:
            optimizations_needed.append("caching")
            
        if not "@validate_request" in function_section:
            optimizations_needed.append("validation")
            
        if not "@handle_api_errors" in function_section:
            optimizations_needed.append("error_handling")
            
        if not "@monitor_performance" in function_section:
            optimizations_needed.append("performance")
            
        if "get_all(" in function_section and "limit" not in function_section:
            optimizations_needed.append("pagination")
            
        if "frappe.db.sql" in function_section:
            optimizations_needed.append("query_optimization")
            
        if "for " in function_section and "frappe." in function_section:
            optimizations_needed.append("batch_processing")
            
        return optimizations_needed
    
    def _extract_function(self, content, function_name):
        """Extract function code from file content"""
        lines = content.split('\n')
        start = None
        indent_level = None
        
        for i, line in enumerate(lines):
            if f"def {function_name}" in line:
                start = i
                indent_level = len(line) - len(line.lstrip())
                break
                
        if start is None:
            return ""
            
        function_lines = [lines[start]]
        for i in range(start + 1, len(lines)):
            line = lines[i]
            if line.strip() and len(line) - len(line.lstrip()) <= indent_level:
                break
            function_lines.append(line)
            
        return '\n'.join(function_lines)
    
    def generate_optimization_code(self, endpoint_name, optimizations):
        """Generate optimized code for an endpoint"""
        decorators = []
        imports = set()
        
        if "caching" in optimizations:
            decorators.append("@cache_with_ttl(ttl=300)")
            imports.add("from verenigingen.utils.error_handling import cache_with_ttl")
            
        if "validation" in optimizations:
            decorators.append("@validate_request")
            imports.add("from verenigingen.utils.error_handling import validate_request")
            
        if "error_handling" in optimizations:
            decorators.append("@handle_api_errors")
            imports.add("from verenigingen.utils.error_handling import handle_api_errors")
            
        if "performance" in optimizations:
            decorators.append("@monitor_performance")
            imports.add("from verenigingen.utils.performance_monitoring import monitor_performance")
            
        template = f"""
# Add these imports at the top of the file:
{chr(10).join(sorted(imports))}

# Apply these decorators to {endpoint_name}:
{chr(10).join(decorators)}
@frappe.whitelist()
def {endpoint_name}(**kwargs):
    # Existing function code...
"""
        
        if "pagination" in optimizations:
            template += """
    # Add pagination:
    limit = int(kwargs.get('limit', 100))
    offset = int(kwargs.get('offset', 0))
    
    # In your query:
    results = frappe.get_all(
        doctype,
        filters=filters,
        limit=limit,
        start=offset
    )
"""
        
        if "query_optimization" in optimizations:
            template += """
    # Optimize queries:
    from verenigingen.utils.performance_monitoring import get_query_optimization
    
    # Use optimized query:
    results = get_query_optimization().execute_optimized_query(
        query,
        values,
        as_dict=True
    )
"""
        
        if "batch_processing" in optimizations:
            template += """
    # Use batch processing:
    from verenigingen.utils.batch_processor import BatchProcessor
    
    processor = BatchProcessor(batch_size=100)
    results = processor.process_items(
        items,
        processing_function
    )
"""
        
        return template


def get_unoptimized_endpoints():
    """Get list of endpoints that need optimization"""
    # Based on the analysis, these endpoints need optimization
    unoptimized = [
        {
            "file": "verenigingen/api/sepa_reconciliation.py",
            "endpoints": [
                "create_sepa_reconciliation",
                "get_sepa_reconciliation", 
                "submit_sepa_reconciliation",
                "get_unmatched_transactions"
            ]
        },
        {
            "file": "verenigingen/api/suspension.py",
            "endpoints": [
                "create_bulk_suspensions",
                "process_suspension",
                "get_suspension_list"
            ]
        },
        {
            "file": "verenigingen/api/payments.py",
            "endpoints": [
                "get_payment_dashboard_data",
                "get_payment_stats"
            ]
        },
        {
            "file": "verenigingen/api/termination.py",
            "endpoints": [
                "process_bulk_terminations",
                "get_termination_dashboard"
            ]
        },
        {
            "file": "verenigingen/api/dd_batch.py",
            "endpoints": [
                "create_dd_batch",
                "process_dd_batch",
                "get_dd_batch_status"
            ]
        },
        {
            "file": "verenigingen/api/member.py",
            "endpoints": [
                "get_member_details",  # Needs caching
                "search_members",      # Needs pagination
                "bulk_update_members"  # Needs batch processing
            ]
        },
        {
            "file": "verenigingen/api/email_utils.py",
            "endpoints": [
                "send_bulk_email",
                "get_email_templates",
                "preview_email_template"
            ]
        }
    ]
    
    return unoptimized


def generate_optimization_report():
    """Generate a report of needed optimizations"""
    optimizer = APIOptimizationPlan()
    report = {
        "summary": {
            "total_endpoints": 0,
            "optimized": 4,  # From analysis
            "unoptimized": 0,
            "optimization_coverage": 0
        },
        "endpoints": []
    }
    
    unoptimized = get_unoptimized_endpoints()
    
    for api_file in unoptimized:
        for endpoint in api_file["endpoints"]:
            report["summary"]["total_endpoints"] += 1
            report["summary"]["unoptimized"] += 1
            
            # Analyze what optimizations are needed
            needed = []
            if "get_" in endpoint:
                needed.append("caching")
            if "bulk_" in endpoint or "process_" in endpoint:
                needed.append("batch_processing")
            if "list" in endpoint or "search" in endpoint:
                needed.append("pagination")
                
            # All endpoints need these
            needed.extend(["validation", "error_handling", "performance"])
            
            report["endpoints"].append({
                "file": api_file["file"],
                "function": endpoint,
                "optimizations_needed": needed,
                "priority": "high" if len(needed) > 4 else "medium"
            })
    
    report["summary"]["total_endpoints"] += report["summary"]["optimized"]
    report["summary"]["optimization_coverage"] = (
        report["summary"]["optimized"] / report["summary"]["total_endpoints"] * 100
    )
    
    return report


def apply_optimization_to_endpoint(file_path, function_name, optimizations):
    """Apply optimizations to a specific endpoint"""
    print(f"\nOptimizing {function_name} in {file_path}")
    print(f"Optimizations to apply: {', '.join(optimizations)}")
    
    optimizer = APIOptimizationPlan()
    
    # Generate optimization code
    code = optimizer.generate_optimization_code(function_name, optimizations)
    
    print("\nGenerated optimization code:")
    print("="*50)
    print(code)
    print("="*50)
    
    # In a real implementation, this would modify the file
    # For now, we just show what needs to be done
    
    return code


def create_optimization_script():
    """Create a script to apply all optimizations"""
    script = """#!/usr/bin/env python3
# Auto-generated API optimization script

import os
import sys
from pathlib import Path

# Add optimizations to these endpoints:

"""
    
    report = generate_optimization_report()
    
    for endpoint in report["endpoints"]:
        if endpoint["priority"] == "high":
            script += f"""
# {endpoint['file']} - {endpoint['function']}
# Optimizations needed: {', '.join(endpoint['optimizations_needed'])}
# TODO: Apply decorators and implement optimizations

"""
    
    return script


if __name__ == "__main__":
    print("API Optimization Analysis")
    print("="*50)
    
    report = generate_optimization_report()
    
    print(f"\nTotal Endpoints: {report['summary']['total_endpoints']}")
    print(f"Optimized: {report['summary']['optimized']}")
    print(f"Unoptimized: {report['summary']['unoptimized']}")
    print(f"Coverage: {report['summary']['optimization_coverage']:.1f}%")
    
    print("\nHigh Priority Optimizations Needed:")
    print("-"*50)
    
    for endpoint in report["endpoints"]:
        if endpoint["priority"] == "high":
            print(f"\n{endpoint['file']}")
            print(f"  Function: {endpoint['function']}")
            print(f"  Optimizations: {', '.join(endpoint['optimizations_needed'])}")
    
    print("\n\nExample Optimization:")
    print("-"*50)
    
    # Show example for one endpoint
    example = report["endpoints"][0]
    apply_optimization_to_endpoint(
        example["file"],
        example["function"],
        example["optimizations_needed"]
    )
    
    # Save report
    with open("api_optimization_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    print("\n✅ Report saved to api_optimization_report.json")