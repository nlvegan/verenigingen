#!/usr/bin/env python3
"""
Comprehensive Test Runner for Verenigingen App
Runs all organized tests in the new structure
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

class VerenigingenTestRunner:
    """Test runner for the reorganized test structure"""
    
    def __init__(self):
        self.test_root = Path(__file__).parent
        self.app_root = self.test_root.parent.parent
        
    def get_test_categories(self):
        """Get all available test categories"""
        categories = {
            'frontend': {
                'unit': self.test_root / 'frontend' / 'unit',
                'integration': self.test_root / 'frontend' / 'integration', 
                'components': self.test_root / 'frontend' / 'components'
            },
            'backend': {
                'unit': self.test_root / 'backend' / 'unit',
                'integration': self.test_root / 'backend' / 'integration',
                'workflows': self.test_root / 'backend' / 'workflows',
                'components': self.test_root / 'backend' / 'components',
                'business_logic': self.test_root / 'backend' / 'business_logic',
                'validation': self.test_root / 'backend' / 'validation',
                'performance': self.test_root / 'backend' / 'performance',
                'security': self.test_root / 'backend' / 'security',
                'comprehensive': self.test_root / 'backend' / 'comprehensive',
                'data_migration': self.test_root / 'backend' / 'data_migration',
                'optimization': self.test_root / 'backend' / 'optimization',
                'features': self.test_root / 'backend' / 'features'
            },
            'utils': self.test_root / 'utils',
            'fixtures': self.test_root / 'fixtures'
        }
        return categories
        
    def run_python_tests(self, test_path, pattern="test_*.py"):
        """Run Python tests in a directory"""
        if not test_path.exists():
            print(f"⚠️  Directory {test_path} does not exist")
            return True
            
        test_files = list(test_path.glob(pattern))
        if not test_files:
            print(f"📝 No tests found in {test_path}")
            return True
            
        print(f"🐍 Running Python tests in {test_path.relative_to(self.test_root)}")
        
        success = True
        for test_file in test_files:
            try:
                # Use bench to run tests with proper Frappe environment
                module_path = str(test_file.relative_to(self.app_root)).replace('/', '.').replace('.py', '')
                result = subprocess.run([
                    'bench', '--site', 'dev.veganisme.net', 'run-tests', '--module', module_path
                ], cwd='/home/frappe/frappe-bench', capture_output=True, text=True)
                
                if result.returncode == 0:
                    print(f"  ✅ {test_file.name}")
                else:
                    print(f"  ❌ {test_file.name}")
                    print(f"     Error: {result.stderr}")
                    success = False
                    
            except Exception as e:
                print(f"  💥 {test_file.name} - Exception: {e}")
                success = False
                
        return success
        
    def run_javascript_tests(self, test_path):
        """Run JavaScript tests"""
        if not test_path.exists():
            print(f"⚠️  Directory {test_path} does not exist")
            return True
            
        js_files = list(test_path.glob("*.js")) + list(test_path.glob("*.spec.js"))
        if not js_files:
            print(f"📝 No JavaScript tests found in {test_path}")
            return True
            
        print(f"🟨 JavaScript tests found in {test_path.relative_to(self.test_root)}")
        print("   Note: JavaScript tests require manual execution with Node.js test runner")
        
        for js_file in js_files:
            print(f"  📄 {js_file.name}")
            
        return True
        
    def run_category_tests(self, category, subcategory=None):
        """Run tests for a specific category"""
        categories = self.get_test_categories()
        
        if category not in categories:
            print(f"❌ Unknown category: {category}")
            return False
            
        if isinstance(categories[category], dict):
            if subcategory:
                if subcategory not in categories[category]:
                    print(f"❌ Unknown subcategory: {subcategory} in {category}")
                    return False
                test_path = categories[category][subcategory]
                return self._run_tests_in_path(test_path, category)
            else:
                # Run all subcategories
                success = True
                for sub, path in categories[category].items():
                    if not self._run_tests_in_path(path, f"{category}/{sub}"):
                        success = False
                return success
        else:
            test_path = categories[category]
            return self._run_tests_in_path(test_path, category)
            
    def _run_tests_in_path(self, test_path, category_name):
        """Run tests in a specific path"""
        print(f"\\n📁 Running {category_name} tests...")
        
        if 'frontend' in category_name.lower():
            return self.run_javascript_tests(test_path)
        else:
            return self.run_python_tests(test_path)
            
    def run_all_tests(self):
        """Run all tests in the organized structure"""
        print("🚀 Running All Verenigingen Tests")
        print("=" * 50)
        
        categories = self.get_test_categories()
        overall_success = True
        
        # Run frontend tests
        print("\\n🎨 FRONTEND TESTS")
        print("-" * 30)
        if not self.run_category_tests('frontend'):
            overall_success = False
            
        # Run backend tests  
        print("\\n🔧 BACKEND TESTS")
        print("-" * 30)
        if not self.run_category_tests('backend'):
            overall_success = False
            
        # Run utility tests
        print("\\n🛠️  UTILITY TESTS")
        print("-" * 30)
        if not self.run_category_tests('utils'):
            overall_success = False
            
        # Run fixture tests
        print("\\n📋 FIXTURE TESTS")
        print("-" * 30)
        if not self.run_category_tests('fixtures'):
            overall_success = False
            
        print("\\n" + "=" * 50)
        if overall_success:
            print("🎉 All tests completed successfully!")
        else:
            print("⚠️  Some tests failed. Check output above for details.")
            
        return overall_success
        
    def list_categories(self):
        """List all available test categories"""
        categories = self.get_test_categories()
        
        print("📂 Available Test Categories:")
        print("=" * 40)
        
        for category, subcats in categories.items():
            if isinstance(subcats, dict):
                print(f"\\n📁 {category}/")
                for subcat, path in subcats.items():
                    test_count = len(list(path.glob("*.py"))) if path.exists() else 0
                    js_count = len(list(path.glob("*.js"))) if path.exists() else 0
                    total = test_count + js_count
                    print(f"  └── {subcat}/ ({total} files)")
            else:
                test_count = len(list(subcats.glob("*.py"))) if subcats.exists() else 0
                print(f"\\n📄 {category}/ ({test_count} files)")

def main():
    parser = argparse.ArgumentParser(description='Run Verenigingen tests')
    parser.add_argument('--category', '-c', help='Test category to run')
    parser.add_argument('--subcategory', '-s', help='Test subcategory to run')
    parser.add_argument('--list', '-l', action='store_true', help='List available categories')
    parser.add_argument('--all', '-a', action='store_true', help='Run all tests (default)')
    
    args = parser.parse_args()
    
    runner = VerenigingenTestRunner()
    
    if args.list:
        runner.list_categories()
        return
        
    if args.category:
        success = runner.run_category_tests(args.category, args.subcategory)
    else:
        success = runner.run_all_tests()
        
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()