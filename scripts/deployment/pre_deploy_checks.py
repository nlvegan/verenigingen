#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pre-deployment Checks
Validates the codebase is ready for deployment
"""

import os
import sys
import json
import subprocess
from pathlib import Path
import re


class PreDeploymentChecker:
    """Run pre-deployment validation checks"""
    
    def __init__(self):
        self.app_path = Path(__file__).parent.parent.parent
        self.errors = []
        self.warnings = []
        self.info = []
        
    def check_python_syntax(self):
        """Check all Python files for syntax errors"""
        print("🐍 Checking Python syntax...")
        
        python_files = list(self.app_path.rglob("*.py"))
        
        for file_path in python_files:
            if "node_modules" in str(file_path) or ".git" in str(file_path):
                continue
                
            try:
                with open(file_path, 'r') as f:
                    compile(f.read(), file_path, 'exec')
            except SyntaxError as e:
                self.errors.append(f"Syntax error in {file_path}: {e}")
                
        if not self.errors:
            self.info.append(f"✅ All {len(python_files)} Python files have valid syntax")
            
    def check_imports(self):
        """Check for missing imports"""
        print("📦 Checking imports...")
        
        import_errors = []
        
        # Common imports to check
        test_imports = [
            "import frappe",
            "from frappe import _",
            "from verenigingen.utils import *"
        ]
        
        # Try importing main modules
        sys.path.insert(0, str(self.app_path))
        
        try:
            import verenigingen
            self.info.append("✅ Main module imports successfully")
        except ImportError as e:
            self.errors.append(f"Cannot import main module: {e}")
            
    def check_json_files(self):
        """Validate all JSON files"""
        print("📄 Checking JSON files...")
        
        json_files = list(self.app_path.rglob("*.json"))
        valid_count = 0
        
        for file_path in json_files:
            if "node_modules" in str(file_path) or ".git" in str(file_path):
                continue
                
            try:
                with open(file_path, 'r') as f:
                    json.load(f)
                valid_count += 1
            except json.JSONDecodeError as e:
                self.errors.append(f"Invalid JSON in {file_path}: {e}")
                
        self.info.append(f"✅ {valid_count}/{len(json_files)} JSON files are valid")
        
    def check_doctype_consistency(self):
        """Check DocType JSON files for consistency"""
        print("🏗️  Checking DocType consistency...")
        
        doctype_path = self.app_path / "verenigingen" / "verenigingen" / "doctype"
        
        if not doctype_path.exists():
            self.warnings.append("DocType directory not found")
            return
            
        for doctype_dir in doctype_path.iterdir():
            if not doctype_dir.is_dir():
                continue
                
            json_file = doctype_dir / f"{doctype_dir.name}.json"
            py_file = doctype_dir / f"{doctype_dir.name}.py"
            
            if json_file.exists():
                with open(json_file, 'r') as f:
                    try:
                        data = json.load(f)
                        
                        # Check required fields
                        if "name" not in data:
                            self.errors.append(f"Missing 'name' in {json_file}")
                            
                        if "fields" not in data:
                            self.warnings.append(f"No fields defined in {json_file}")
                            
                        # Check if Python file exists
                        if not py_file.exists():
                            self.warnings.append(f"Missing Python file for {doctype_dir.name}")
                            
                    except json.JSONDecodeError:
                        pass  # Already caught in check_json_files
                        
        self.info.append("✅ DocType consistency check complete")
        
    def check_hooks_file(self):
        """Validate hooks.py configuration"""
        print("🔗 Checking hooks.py...")
        
        hooks_file = self.app_path / "verenigingen" / "hooks.py"
        
        if not hooks_file.exists():
            self.errors.append("hooks.py not found!")
            return
            
        with open(hooks_file, 'r') as f:
            content = f.read()
            
        # Check for required configurations
        required_configs = [
            "app_name",
            "app_title",
            "app_publisher",
            "app_version"
        ]
        
        for config in required_configs:
            if config not in content:
                self.errors.append(f"Missing '{config}' in hooks.py")
                
        # Check for common issues
        if "fixtures" in content:
            self.info.append("📌 Fixtures defined in hooks.py")
            
        if "scheduler_events" in content:
            self.info.append("⏰ Scheduler events configured")
            
        self.info.append("✅ hooks.py validation complete")
        
    def check_requirements(self):
        """Check Python dependencies"""
        print("📋 Checking requirements.txt...")
        
        req_file = self.app_path / "requirements.txt"
        
        if not req_file.exists():
            self.warnings.append("requirements.txt not found")
            return
            
        with open(req_file, 'r') as f:
            requirements = f.read().strip().split('\n')
            
        if not requirements or all(not line.strip() for line in requirements):
            self.warnings.append("requirements.txt is empty")
        else:
            self.info.append(f"✅ Found {len(requirements)} Python dependencies")
            
        # Check for problematic dependencies
        for req in requirements:
            if "git+" in req:
                self.warnings.append(f"Git dependency found: {req}")
                
    def check_package_json(self):
        """Check Node.js dependencies"""
        print("📦 Checking package.json...")
        
        package_file = self.app_path / "package.json"
        
        if package_file.exists():
            with open(package_file, 'r') as f:
                try:
                    package_data = json.load(f)
                    
                    deps = package_data.get("dependencies", {})
                    dev_deps = package_data.get("devDependencies", {})
                    
                    self.info.append(f"✅ Found {len(deps)} dependencies and {len(dev_deps)} dev dependencies")
                    
                except json.JSONDecodeError:
                    pass  # Already caught in check_json_files
        else:
            self.info.append("📦 No package.json found (OK if no JS dependencies)")
            
    def check_security_issues(self):
        """Basic security checks"""
        print("🔒 Running security checks...")
        
        # Check for common security issues
        patterns = [
            (r'password\s*=\s*["\'][^"\']+["\']', "Hardcoded password found"),
            (r'api_key\s*=\s*["\'][^"\']+["\']', "Hardcoded API key found"),
            (r'secret\s*=\s*["\'][^"\']+["\']', "Hardcoded secret found"),
            (r'eval\s*\(', "Use of eval() found - potential security risk"),
            (r'pickle\.loads?\s*\(', "Use of pickle found - potential security risk"),
            (r'os\.system\s*\(', "Use of os.system found - use subprocess instead"),
        ]
        
        python_files = list(self.app_path.rglob("*.py"))
        
        for file_path in python_files:
            if "test" in str(file_path) or ".git" in str(file_path):
                continue
                
            with open(file_path, 'r') as f:
                content = f.read()
                
            for pattern, message in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    self.warnings.append(f"{message} in {file_path}")
                    
        self.info.append("✅ Security check complete")
        
    def check_database_queries(self):
        """Check for potentially problematic database queries"""
        print("🗄️  Checking database queries...")
        
        python_files = list(self.app_path.rglob("*.py"))
        
        issues = []
        
        for file_path in python_files:
            if ".git" in str(file_path):
                continue
                
            with open(file_path, 'r') as f:
                content = f.read()
                
            # Check for non-parameterized queries
            if "frappe.db.sql" in content:
                # Look for string formatting in SQL
                if re.search(r'frappe\.db\.sql\s*\([^)]*%[^)]*\)', content):
                    issues.append(f"Potential SQL injection in {file_path}")
                    
            # Check for missing limit clauses
            if re.search(r'frappe\.get_all\s*\([^)]+\)', content):
                if "limit" not in content:
                    self.warnings.append(f"get_all without limit in {file_path}")
                    
        if issues:
            for issue in issues:
                self.errors.append(issue)
        else:
            self.info.append("✅ Database queries look safe")
            
    def check_translations(self):
        """Check for untranslated strings"""
        print("🌍 Checking translations...")
        
        python_files = list(self.app_path.rglob("*.py"))
        js_files = list(self.app_path.rglob("*.js"))
        
        untranslated = 0
        
        for file_path in python_files + js_files:
            if "node_modules" in str(file_path) or ".git" in str(file_path):
                continue
                
            with open(file_path, 'r') as f:
                content = f.read()
                
            # Look for potential untranslated strings
            if file_path.suffix == '.py':
                # Check for frappe.msgprint without _()
                if re.search(r'frappe\.msgprint\s*\(["\'][^"\']+["\']', content):
                    if not re.search(r'frappe\.msgprint\s*\(_\(', content):
                        untranslated += 1
                        
        if untranslated > 0:
            self.warnings.append(f"Found {untranslated} potentially untranslated strings")
        else:
            self.info.append("✅ Translation check complete")
            
    def run_all_checks(self):
        """Run all pre-deployment checks"""
        print("🚀 Running pre-deployment checks...\n")
        
        self.check_python_syntax()
        self.check_imports()
        self.check_json_files()
        self.check_doctype_consistency()
        self.check_hooks_file()
        self.check_requirements()
        self.check_package_json()
        self.check_security_issues()
        self.check_database_queries()
        self.check_translations()
        
        # Generate report
        self.generate_report()
        
        # Exit with appropriate code
        if self.errors:
            sys.exit(1)
        elif self.warnings:
            sys.exit(0)  # Warnings don't fail the build
        else:
            sys.exit(0)
            
    def generate_report(self):
        """Generate deployment readiness report"""
        print("\n" + "="*50)
        print("📊 PRE-DEPLOYMENT CHECK SUMMARY")
        print("="*50)
        
        # Info messages
        if self.info:
            print("\n✅ PASSED CHECKS:")
            for msg in self.info:
                print(f"  {msg}")
                
        # Warnings
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for msg in self.warnings:
                print(f"  - {msg}")
                
        # Errors
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for msg in self.errors:
                print(f"  - {msg}")
                
        # Summary
        print("\n" + "-"*50)
        if self.errors:
            print("❌ DEPLOYMENT BLOCKED - Fix errors before deploying")
        elif self.warnings:
            print("⚠️  DEPLOYMENT ALLOWED - But consider fixing warnings")
        else:
            print("✅ ALL CHECKS PASSED - Ready for deployment!")
            
        # Save report
        report = {
            "timestamp": subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ']).decode().strip(),
            "passed": len(self.info),
            "warnings": len(self.warnings),
            "errors": len(self.errors),
            "details": {
                "info": self.info,
                "warnings": self.warnings,
                "errors": self.errors
            }
        }
        
        with open("pre-deployment-report.json", "w") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    checker = PreDeploymentChecker()
    checker.run_all_checks()