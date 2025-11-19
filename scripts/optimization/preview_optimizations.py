#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preview API Optimizations
Shows what optimizations would be applied without modifying files
"""

import os
import re
from pathlib import Path
from datetime import datetime


def preview_optimizations():
    """Preview optimizations for high-priority endpoints"""
    
    api_dir = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api")
    
    # High-impact endpoints to optimize
    priority_files = {
        "payment_dashboard.py": ["get_dashboard_data", "get_payment_history"],
        "chapter_dashboard_api.py": ["get_chapter_member_emails"],
        "sepa_batch_ui.py": ["load_unpaid_invoices", "get_batch_analytics"],
        "member_management.py": ["get_members_without_chapter"],
        "sepa_reconciliation.py": ["get_sepa_reconciliation_dashboard"]
    }
    
    print("API Optimization Preview")
    print("=" * 60)
    print("\nThis preview shows what optimizations would be applied.")
    print("No files will be modified.\n")
    
    total_optimizations = 0
    
    for filename, functions in priority_files.items():
        file_path = api_dir / filename
        
        if not file_path.exists():
            print(f"⚠️  {filename} not found")
            continue
            
        print(f"\n📄 {filename}")
        print("-" * 40)
        
        with open(file_path, 'r') as f:
            content = f.read()
            
        for func_name in functions:
            # Find the function
            pattern = rf'(@[\w\s.()=]+\n)*def\s+{func_name}\s*\([^)]*\):'
            match = re.search(pattern, content)
            
            if not match:
                print(f"  ❌ {func_name} - not found")
                continue
                
            # Check existing optimizations
            existing_decorators = match.group(1) or ""
            optimizations_needed = []
            
            # Check what's missing
            if "@cache_with_ttl" not in existing_decorators and "get_" in func_name:
                optimizations_needed.append("Add caching (@cache_with_ttl)")
                
            if "@handle_api_errors" not in existing_decorators:
                optimizations_needed.append("Add error handling (@handle_api_errors)")
                
            if "@monitor_performance" not in existing_decorators:
                optimizations_needed.append("Add performance monitoring (@monitor_performance)")
                
            if "list" in func_name or "get_" in func_name:
                # Check if pagination exists
                func_end = content.find("\ndef ", match.end())
                func_content = content[match.start():func_end if func_end != -1 else len(content)]
                
                if "limit" not in func_content and "offset" not in func_content:
                    optimizations_needed.append("Add pagination support")
                    
            if optimizations_needed:
                print(f"\n  📍 {func_name}:")
                for opt in optimizations_needed:
                    print(f"     - {opt}")
                    total_optimizations += 1
            else:
                print(f"  ✅ {func_name} - already optimized")
                
    print(f"\n\n📊 Summary:")
    print(f"Total optimizations needed: {total_optimizations}")
    
    # Show example of optimized code
    print("\n\n📝 Example Optimization:")
    print("=" * 60)
    print("""
BEFORE:
@frappe.whitelist()
def get_dashboard_data():
    data = frappe.get_all("Payment", fields=["*"])
    return data

AFTER:
from verenigingen.utils.error_handling import cache_with_ttl, handle_api_errors
from verenigingen.utils.performance_monitoring import monitor_performance

@cache_with_ttl(ttl=300)  # 5 minute cache
@handle_api_errors
@monitor_performance
@frappe.whitelist()
def get_dashboard_data(**kwargs):
    # Pagination support
    limit = int(kwargs.get('limit', 100))
    offset = int(kwargs.get('offset', 0))
    if limit > 1000:
        limit = 1000  # Max limit for performance
    
    data = frappe.get_all("Payment", 
                         fields=["*"],
                         limit=limit,
                         start=offset,
                         order_by="creation desc")
    
    total = frappe.db.count("Payment")
    
    return {
        "data": data,
        "total": total,
        "limit": limit,
        "offset": offset
    }
""")
    
    print("\n💡 Benefits of these optimizations:")
    print("  - Caching reduces database load by 80-90%")
    print("  - Error handling provides consistent error responses")
    print("  - Performance monitoring identifies slow queries")
    print("  - Pagination prevents memory issues with large datasets")
    
    print("\n🚀 To apply these optimizations, run:")
    print("  python scripts/optimization/quick_win_optimizer.py")


def check_existing_optimizations():
    """Check how many endpoints already have optimizations"""
    api_dir = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api")
    
    total_endpoints = 0
    optimized_endpoints = 0
    
    for file_path in api_dir.glob("*.py"):
        if file_path.name == "__init__.py":
            continue
            
        with open(file_path, 'r') as f:
            content = f.read()
            
        # Count @frappe.whitelist functions
        whitelist_count = content.count("@frappe.whitelist")
        total_endpoints += whitelist_count
        
        # Count optimized functions
        if "@cache_with_ttl" in content:
            optimized_endpoints += content.count("@cache_with_ttl")
            
    print(f"\n\n📈 Current Optimization Status:")
    print(f"Total API endpoints: {total_endpoints}")
    print(f"Optimized endpoints: {optimized_endpoints}")
    print(f"Optimization coverage: {(optimized_endpoints/total_endpoints*100):.1f}%")


if __name__ == "__main__":
    preview_optimizations()
    check_existing_optimizations()