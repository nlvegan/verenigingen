#!/usr/bin/env python3
"""
Debug script for the enhanced validator
"""

from pathlib import Path
import json

# Load config
def load_config():
    config_path = Path(__file__).parent / "validator_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}

def test_path_resolution():
    """Test path resolution logic"""
    project_root = Path(".")
    config = load_config()
    
    print("Testing path resolution...")
    print(f"Project root: {project_root.resolve()}")
    print(f"Config loaded: {len(config)} settings")
    
    # Test Python file discovery
    python_files = list(project_root.glob("**/*.py"))
    print(f"Total Python files found: {len(python_files)}")
    
    # Test exclusion logic
    exclude_patterns = config.get('exclude_patterns', [])
    print(f"Exclude patterns: {exclude_patterns}")
    
    excluded_count = 0
    for py_file in python_files[:10]:  # Test first 10
        path_str = str(py_file).lower()
        is_excluded = False
        
        # Check standard exclusions
        if any(part in str(py_file) for part in ['.git', '__pycache__', 'node_modules']):
            is_excluded = True
            
        # Check config exclusions
        for pattern in exclude_patterns:
            pattern_parts = pattern.replace('**', '').replace('*', '').split('/')
            if any(part and part in path_str for part in pattern_parts):
                is_excluded = True
                break
        
        if is_excluded:
            excluded_count += 1
            print(f"EXCLUDED: {py_file}")
        else:
            print(f"INCLUDED: {py_file}")
    
    print(f"Excluded {excluded_count} out of first 10 files")
    
    # Test JavaScript file discovery
    js_files = list(project_root.glob("**/*.js"))
    print(f"Total JavaScript files found: {len(js_files)}")
    
    # Look for specific whitelisted functions
    print("\nLooking for specific methods...")
    test_methods = ["derive_bic_from_iban", "get_billing_amount"]
    
    for method in test_methods:
        print(f"\nSearching for {method}:")
        
        # Search in Python files
        import re
        pattern = rf"def\s+{method}\s*\("
        
        for py_file in python_files:
            if any(part in str(py_file) for part in ['.git', '__pycache__', 'node_modules', 'archived']):
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if re.search(pattern, content):
                    print(f"  Found in: {py_file}")
                    
                    # Check if it has whitelist decorator
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if re.search(pattern, line):
                            # Look backwards for decorator
                            for j in range(max(0, i-5), i):
                                if '@frappe.whitelist' in lines[j]:
                                    print(f"    ✓ Has @frappe.whitelist() decorator")
                                    break
                            else:
                                print(f"    ✗ Missing @frappe.whitelist() decorator")
                            break
                            
            except Exception as e:
                print(f"  Error reading {py_file}: {e}")
    
    # Test framework method detection
    print(f"\nTesting framework method detection:")
    framework_methods = config.get('framework_methods', [])
    test_framework = ["frappe.client.get", "frappe.db.get_value"]
    
    for method in test_framework:
        if method in framework_methods:
            print(f"  ✓ {method} correctly identified as framework method")
        else:
            print(f"  ✗ {method} not in framework methods list")

if __name__ == "__main__":
    test_path_resolution()