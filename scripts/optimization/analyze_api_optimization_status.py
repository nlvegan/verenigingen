#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyze API Optimization Status
Checks which API endpoints still need optimization
"""

import os
import re
from pathlib import Path


def analyze_api_files():
    """Analyze all API files for optimization status"""
    api_dir = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api")
    
    optimization_markers = {
        "cache_with_ttl": "Caching",
        "handle_api_errors": "Error Handling",
        "validate_request": "Input Validation",
        "monitor_performance": "Performance Monitoring",
        "batch_processor": "Batch Processing",
        "limit.*offset": "Pagination"
    }
    
    results = {
        "optimized": [],
        "partially_optimized": [],
        "unoptimized": [],
        "total_endpoints": 0
    }
    
    # Scan all Python files in API directory
    for api_file in api_dir.glob("*.py"):
        if api_file.name == "__init__.py":
            continue
            
        with open(api_file, 'r') as f:
            content = f.read()
            
        # Find all function definitions
        functions = re.findall(r'^def\s+(\w+)\s*\(', content, re.MULTILINE)
        whitelisted_functions = []
        
        # Check for @frappe.whitelist() decorated functions
        for func in functions:
            # Look for the function with its decorator
            func_pattern = r'(@[\w.]+\s*\n)*\s*def\s+' + func + r'\s*\('
            if re.search(func_pattern, content):
                if '@frappe.whitelist' in content[:content.find(f'def {func}')]:
                    whitelisted_functions.append(func)
        
        if not whitelisted_functions:
            continue
            
        results["total_endpoints"] += len(whitelisted_functions)
        
        # Check optimization status for each endpoint
        file_status = {
            "file": api_file.name,
            "endpoints": {}
        }
        
        for func in whitelisted_functions:
            # Extract function content
            func_start = content.find(f'def {func}')
            func_content = content[max(0, func_start-500):func_start+1000]
            
            optimizations = {}
            for marker, opt_type in optimization_markers.items():
                if re.search(marker, func_content, re.IGNORECASE):
                    optimizations[opt_type] = True
                else:
                    optimizations[opt_type] = False
            
            file_status["endpoints"][func] = optimizations
            
            # Categorize endpoint
            opt_count = sum(optimizations.values())
            if opt_count >= 4:
                results["optimized"].append(f"{api_file.name}::{func}")
            elif opt_count >= 2:
                results["partially_optimized"].append(f"{api_file.name}::{func}")
            else:
                results["unoptimized"].append(f"{api_file.name}::{func}")
        
    return results


def generate_optimization_recommendations():
    """Generate specific recommendations for each unoptimized endpoint"""
    recommendations = {}
    
    # Key endpoints that need optimization
    critical_endpoints = {
        "sepa_reconciliation.py": {
            "create_sepa_reconciliation": ["caching", "batch_processing", "error_handling"],
            "get_unmatched_transactions": ["pagination", "caching", "performance_monitoring"]
        },
        "suspension.py": {
            "create_bulk_suspensions": ["batch_processing", "validation", "error_handling"],
            "get_suspension_list": ["pagination", "caching"]
        },
        "payments.py": {
            "get_payment_dashboard_data": ["caching", "performance_monitoring"],
            "process_bulk_payments": ["batch_processing", "error_handling"]
        },
        "termination.py": {
            "process_bulk_terminations": ["batch_processing", "validation", "error_handling"],
            "get_termination_dashboard": ["caching", "pagination"]
        }
    }
    
    for file, endpoints in critical_endpoints.items():
        for endpoint, opts in endpoints.items():
            recommendations[f"{file}::{endpoint}"] = opts
            
    return recommendations


def main():
    """Main analysis function"""
    print("API Optimization Status Analysis")
    print("=" * 60)
    
    # Analyze current status
    results = analyze_api_files()
    
    print(f"\nTotal API Endpoints Found: {results['total_endpoints']}")
    print(f"Fully Optimized: {len(results['optimized'])}")
    print(f"Partially Optimized: {len(results['partially_optimized'])}")
    print(f"Unoptimized: {len(results['unoptimized'])}")
    
    optimization_percentage = (len(results['optimized']) / results['total_endpoints'] * 100) if results['total_endpoints'] > 0 else 0
    print(f"\nOptimization Coverage: {optimization_percentage:.1f}%")
    
    # Show unoptimized endpoints
    if results['unoptimized']:
        print("\n❌ Unoptimized Endpoints:")
        print("-" * 60)
        for endpoint in sorted(results['unoptimized'])[:10]:  # Show first 10
            print(f"  - {endpoint}")
        if len(results['unoptimized']) > 10:
            print(f"  ... and {len(results['unoptimized']) - 10} more")
    
    # Show partially optimized
    if results['partially_optimized']:
        print("\n⚠️  Partially Optimized Endpoints:")
        print("-" * 60)
        for endpoint in sorted(results['partially_optimized'])[:5]:  # Show first 5
            print(f"  - {endpoint}")
        if len(results['partially_optimized']) > 5:
            print(f"  ... and {len(results['partially_optimized']) - 5} more")
    
    # Generate recommendations
    print("\n📋 Priority Optimization Tasks:")
    print("-" * 60)
    
    recommendations = generate_optimization_recommendations()
    for endpoint, optimizations in list(recommendations.items())[:5]:
        print(f"\n{endpoint}:")
        print(f"  Recommended optimizations: {', '.join(optimizations)}")
    
    # Summary
    print("\n📊 Summary:")
    print("-" * 60)
    print(f"✅ Progress: {len(results['optimized'])} endpoints fully optimized")
    print(f"⚠️  In Progress: {len(results['partially_optimized'])} endpoints partially optimized")
    print(f"❌ TODO: {len(results['unoptimized'])} endpoints need optimization")
    
    # Next steps
    print("\n🚀 Next Steps:")
    print("-" * 60)
    print("1. Focus on high-traffic endpoints first (dashboard, list views)")
    print("2. Add caching to all GET endpoints")
    print("3. Implement pagination for list endpoints")
    print("4. Add batch processing for bulk operations")
    print("5. Ensure all endpoints have error handling and validation")
    
    return results


if __name__ == "__main__":
    main()