#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Apply API Optimizations
Script to systematically apply optimizations to API endpoints
"""

import os
import re
from pathlib import Path


class APIOptimizer:
    """Apply optimizations to API endpoints"""
    
    def __init__(self):
        self.api_dir = Path("/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api")
        self.optimization_templates = {
            "caching": {
                "decorator": "@cache_with_ttl(ttl=300)",
                "import": "from verenigingen.utils.error_handling import cache_with_ttl",
                "applies_to": ["get_", "fetch_", "list_", "dashboard"]
            },
            "error_handling": {
                "decorator": "@handle_api_errors",
                "import": "from verenigingen.utils.error_handling import handle_api_errors",
                "applies_to": ["all"]
            },
            "validation": {
                "decorator": "@validate_request",
                "import": "from verenigingen.utils.error_handling import validate_request",
                "applies_to": ["create_", "update_", "delete_", "process_"]
            },
            "performance": {
                "decorator": "@monitor_performance",
                "import": "from verenigingen.utils.performance_monitoring import monitor_performance",
                "applies_to": ["all"]
            }
        }
        
    def should_apply_optimization(self, function_name, optimization_type):
        """Determine if optimization should be applied to function"""
        applies_to = self.optimization_templates[optimization_type]["applies_to"]
        
        if "all" in applies_to:
            return True
            
        return any(pattern in function_name for pattern in applies_to)
        
    def add_pagination_to_function(self, function_content, function_name):
        """Add pagination logic to a function"""
        if "limit" in function_content and "offset" in function_content:
            return function_content  # Already has pagination
            
        # Add pagination parameters
        pagination_code = """
    # Pagination parameters
    limit = int(kwargs.get('limit', 100))
    offset = int(kwargs.get('offset', 0))
    
    # Validate pagination
    if limit > 1000:
        limit = 1000  # Max limit
    if offset < 0:
        offset = 0
"""
        
        # Find where to insert (after docstring if exists)
        lines = function_content.split('\n')
        insert_index = 1  # Default after def line
        
        # Skip past docstring
        in_docstring = False
        for i, line in enumerate(lines[1:], 1):
            if '"""' in line or "'''" in line:
                in_docstring = not in_docstring
                if not in_docstring:
                    insert_index = i + 1
                    break
        
        # Insert pagination code
        lines.insert(insert_index, pagination_code)
        
        # Update get_all calls to use pagination
        result = '\n'.join(lines)
        result = re.sub(
            r'frappe\.get_all\((.*?)\)',
            r'frappe.get_all(\1, limit=limit, start=offset)',
            result,
            flags=re.DOTALL
        )
        
        return result
        
    def generate_optimized_file(self, file_path):
        """Generate optimized version of an API file"""
        with open(file_path, 'r') as f:
            content = f.read()
            
        # Track needed imports
        imports_to_add = set()
        
        # Find all whitelisted functions
        pattern = r'(@[\w.]+\s*\n)*@frappe\.whitelist\(\)\s*\ndef\s+(\w+)\s*\([^)]*\):'
        matches = list(re.finditer(pattern, content))
        
        if not matches:
            return None  # No API endpoints in file
            
        # Process each function
        modified_content = content
        
        for match in reversed(matches):  # Process in reverse to maintain positions
            decorators = match.group(1) or ""
            function_name = match.group(2)
            
            # Determine which optimizations to apply
            decorators_to_add = []
            
            # Check if optimizations already applied
            for opt_type, opt_config in self.optimization_templates.items():
                if opt_config["decorator"] not in decorators:
                    if self.should_apply_optimization(function_name, opt_type):
                        decorators_to_add.append(opt_config["decorator"])
                        imports_to_add.add(opt_config["import"])
            
            # Apply decorators
            if decorators_to_add:
                new_decorators = '\n'.join(decorators_to_add) + '\n'
                # Insert before @frappe.whitelist
                pos = match.start()
                modified_content = (
                    modified_content[:pos] + 
                    new_decorators + 
                    modified_content[pos:]
                )
            
            # Add pagination for list/get functions
            if any(pattern in function_name for pattern in ["get_", "list_", "fetch_"]):
                # Extract function content
                func_start = modified_content.find(f"def {function_name}")
                func_end = func_start
                indent_level = 0
                
                # Find end of function
                lines = modified_content[func_start:].split('\n')
                for i, line in enumerate(lines[1:], 1):
                    if line.strip() and not line.startswith((' ', '\t')):
                        func_end = func_start + sum(len(l) + 1 for l in lines[:i])
                        break
                else:
                    func_end = len(modified_content)
                
                # Add pagination
                func_content = modified_content[func_start:func_end]
                paginated_content = self.add_pagination_to_function(func_content, function_name)
                modified_content = (
                    modified_content[:func_start] + 
                    paginated_content + 
                    modified_content[func_end:]
                )
        
        # Add imports at the top
        if imports_to_add:
            import_block = '\n'.join(sorted(imports_to_add)) + '\n\n'
            
            # Find where to insert imports (after existing imports)
            import_pos = 0
            lines = modified_content.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('import ') or line.startswith('from '):
                    import_pos = i + 1
                elif import_pos > 0 and line.strip() and not line.startswith(('import', 'from')):
                    break
            
            lines.insert(import_pos, import_block)
            modified_content = '\n'.join(lines)
        
        return modified_content
        
    def create_optimization_example(self):
        """Create an example of how to optimize an endpoint"""
        example = '''# Example: Optimizing a typical API endpoint

# BEFORE:
@frappe.whitelist()
def get_member_list(chapter=None, status=None):
    """Get list of members"""
    filters = {}
    if chapter:
        filters["chapter"] = chapter
    if status:
        filters["status"] = status
        
    members = frappe.get_all("Member",
        filters=filters,
        fields=["name", "full_name", "email", "status"])
    
    return members

# AFTER:
from verenigingen.utils.error_handling import cache_with_ttl, handle_api_errors, validate_request
from verenigingen.utils.performance_monitoring import monitor_performance

@cache_with_ttl(ttl=300)
@handle_api_errors
@validate_request
@monitor_performance
@frappe.whitelist()
def get_member_list(chapter=None, status=None, **kwargs):
    """Get list of members with pagination and optimization"""
    # Pagination parameters
    limit = int(kwargs.get('limit', 100))
    offset = int(kwargs.get('offset', 0))
    
    # Validate pagination
    if limit > 1000:
        limit = 1000  # Max limit
    if offset < 0:
        offset = 0
    
    filters = {}
    if chapter:
        filters["chapter"] = chapter
    if status:
        filters["status"] = status
        
    members = frappe.get_all("Member",
        filters=filters,
        fields=["name", "full_name", "email", "status"],
        limit=limit,
        start=offset,
        order_by="creation desc")
    
    # Add total count for pagination
    total_count = frappe.db.count("Member", filters)
    
    return {
        "data": members,
        "total": total_count,
        "limit": limit,
        "offset": offset
    }
'''
        return example
        
    def generate_implementation_guide(self):
        """Generate step-by-step implementation guide"""
        guide = '''# API Optimization Implementation Guide

## Phase 1: Critical Endpoints (Week 1)
Focus on high-traffic endpoints that affect user experience:

1. **Dashboard APIs**
   - get_payment_dashboard_data
   - get_chapter_dashboard_data
   - get_volunteer_dashboard_data
   
2. **List/Search APIs**
   - get_member_list
   - search_members
   - get_volunteer_list
   
3. **Bulk Operations**
   - process_bulk_payments
   - create_bulk_suspensions
   - process_bulk_terminations

## Phase 2: CRUD Operations (Week 2)
Optimize create, read, update, delete operations:

1. Add validation to all create/update endpoints
2. Add error handling to all endpoints
3. Add performance monitoring

## Phase 3: Reporting & Analytics (Week 3)
Optimize data-heavy endpoints:

1. Add aggressive caching to report endpoints
2. Implement pagination for large datasets
3. Add query optimization for complex reports

## Implementation Steps:

1. **For each endpoint:**
   ```python
   # Step 1: Add imports
   from verenigingen.utils.error_handling import cache_with_ttl, handle_api_errors
   
   # Step 2: Add decorators
   @cache_with_ttl(ttl=300)  # 5 minutes cache for read operations
   @handle_api_errors        # Standardized error handling
   @monitor_performance      # Performance tracking
   @frappe.whitelist()
   def your_endpoint():
       pass
   ```

2. **For list endpoints:**
   - Add limit/offset parameters
   - Return total count with data
   - Set reasonable max limits (1000 records)

3. **For bulk operations:**
   - Use BatchProcessor utility
   - Process in chunks of 100-500
   - Add progress tracking

4. **For expensive queries:**
   - Add database indexes
   - Use query optimization utility
   - Consider materialized views

## Testing After Optimization:

1. Run performance tests:
   ```bash
   python scripts/performance_benchmark.py
   ```

2. Verify caching works:
   - Call endpoint twice
   - Second call should be faster
   - Check cache headers

3. Test error handling:
   - Send invalid data
   - Verify proper error messages
   - Check error logs

## Monitoring:

After optimization, monitor:
- Response time improvements
- Cache hit rates  
- Error rates
- Database query counts

Use the Performance Dashboard at `/performance_dashboard`
'''
        return guide


def main():
    """Main function to demonstrate optimization approach"""
    optimizer = APIOptimizer()
    
    print("API Optimization Implementation Plan")
    print("=" * 60)
    
    # Show example
    print("\n📋 Optimization Example:")
    print("-" * 60)
    print(optimizer.create_optimization_example())
    
    # Show implementation guide
    print("\n📚 Implementation Guide:")
    print("-" * 60)
    print(optimizer.generate_implementation_guide())
    
    # Demonstrate on one file
    print("\n🔧 Sample Implementation:")
    print("-" * 60)
    
    sample_file = optimizer.api_dir / "member.py"
    if sample_file.exists():
        print(f"Generating optimized version of {sample_file.name}...")
        optimized = optimizer.generate_optimized_file(sample_file)
        
        if optimized:
            # Save to example file
            output_file = optimizer.api_dir.parent / "examples" / "optimized_member_api.py"
            output_file.parent.mkdir(exist_ok=True)
            
            with open(output_file, 'w') as f:
                f.write(optimized)
                
            print(f"✅ Optimized example saved to: {output_file}")
        else:
            print("❌ No API endpoints found in file")
    
    print("\n✅ Next Steps:")
    print("1. Review the optimization example")
    print("2. Start with Phase 1 critical endpoints")
    print("3. Apply optimizations systematically")
    print("4. Test each optimization")
    print("5. Monitor performance improvements")


if __name__ == "__main__":
    main()