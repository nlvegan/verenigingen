#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check for Uncommitted Migrations
Ensures all database migrations are properly tracked
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime


class MigrationChecker:
    """Check for migration issues before deployment"""
    
    def __init__(self):
        self.app_path = Path(__file__).parent.parent.parent
        self.issues = []
        
    def check_patches_txt(self):
        """Verify patches.txt is up to date"""
        print("📝 Checking patches.txt...")
        
        patches_file = self.app_path / "verenigingen" / "patches.txt"
        
        if not patches_file.exists():
            print("  ℹ️  No patches.txt file found (OK if no patches)")
            return True
            
        # Check if patches.txt is tracked in git
        try:
            result = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(patches_file)],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            if result.returncode != 0:
                self.issues.append("patches.txt exists but is not tracked in git")
                
        except Exception as e:
            self.issues.append(f"Error checking git status: {e}")
            
        # Read patches
        with open(patches_file, 'r') as f:
            patches = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            
        print(f"  Found {len(patches)} patches")
        
        # Verify each patch file exists
        for patch in patches:
            patch_path = self.app_path / "verenigingen" / patch.replace('.', '/')
            if not patch_path.with_suffix('.py').exists():
                self.issues.append(f"Patch file not found: {patch}")
                
        return len(self.issues) == 0
        
    def check_doctype_changes(self):
        """Check for uncommitted DocType changes"""
        print("🏗️  Checking for DocType changes...")
        
        try:
            # Get list of modified files
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            if result.returncode != 0:
                self.issues.append("Failed to check git status")
                return False
                
            modified_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            # Check for DocType JSON changes
            doctype_changes = []
            for line in modified_files:
                if line and '.json' in line and 'doctype' in line.lower():
                    status, filename = line[:2], line[3:]
                    if status.strip():  # Any modification
                        doctype_changes.append(filename)
                        
            if doctype_changes:
                print(f"  ⚠️  Found {len(doctype_changes)} uncommitted DocType changes:")
                for change in doctype_changes:
                    print(f"    - {change}")
                self.issues.append("Uncommitted DocType changes found")
                
        except Exception as e:
            self.issues.append(f"Error checking DocType changes: {e}")
            
        return len(self.issues) == 0
        
    def check_field_modifications(self):
        """Check for field additions/modifications that need migrations"""
        print("🔍 Checking for field modifications...")
        
        try:
            # Get diff of DocType JSON files
            result = subprocess.run(
                ["git", "diff", "--name-only", "*.json"],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            if result.returncode == 0 and result.stdout.strip():
                json_files = result.stdout.strip().split('\n')
                
                for json_file in json_files:
                    if 'doctype' in json_file.lower():
                        # Check the actual diff
                        diff_result = subprocess.run(
                            ["git", "diff", json_file],
                            capture_output=True,
                            text=True,
                            cwd=self.app_path
                        )
                        
                        if "fields" in diff_result.stdout:
                            print(f"  ⚠️  Field changes detected in {json_file}")
                            self.check_if_migration_needed(json_file)
                            
        except Exception as e:
            self.issues.append(f"Error checking field modifications: {e}")
            
    def check_if_migration_needed(self, json_file):
        """Determine if a migration is needed for the changes"""
        try:
            # Get the diff details
            result = subprocess.run(
                ["git", "diff", json_file],
                capture_output=True,
                text=True,
                cwd=self.app_path
            )
            
            diff_content = result.stdout
            
            # Check for specific changes that need migrations
            migration_triggers = [
                '"fieldtype":',  # Field type changes
                '"options":',    # Link field changes
                '"default":',    # Default value changes
                '"reqd":',       # Required field changes
                '"unique":',     # Unique constraint changes
            ]
            
            for trigger in migration_triggers:
                if trigger in diff_content:
                    doctype_name = Path(json_file).stem
                    self.issues.append(
                        f"Migration may be needed for {doctype_name} - {trigger} changed"
                    )
                    
        except Exception as e:
            print(f"  Error analyzing {json_file}: {e}")
            
    def check_custom_scripts(self):
        """Check for custom script migrations"""
        print("📜 Checking for custom script changes...")
        
        # Check if there are any custom scripts that might need migration
        custom_patterns = [
            "**/custom_scripts/*.js",
            "**/client_scripts/*.js",
            "**/page/**/*.js"
        ]
        
        for pattern in custom_patterns:
            files = list(self.app_path.glob(pattern))
            if files:
                print(f"  Found {len(files)} custom scripts")
                
    def generate_migration_template(self):
        """Generate a migration template if needed"""
        if self.issues:
            print("\n📋 Migration template needed!")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            template = f'''# -*- coding: utf-8 -*-
"""
Migration: {timestamp}
Description: Add description here
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
    """
    Run the migration
    """
    # Example: Add custom fields
    # custom_fields = {{
    #     "DocType Name": [
    #         {{
    #             "fieldname": "field_name",
    #             "label": "Field Label",
    #             "fieldtype": "Data",
    #             "insert_after": "existing_field"
    #         }}
    #     ]
    # }}
    # create_custom_fields(custom_fields)
    
    # Example: Update data
    # frappe.db.sql("""
    #     UPDATE `tabDocType`
    #     SET field = %s
    #     WHERE condition = %s
    # """, (value, condition))
    
    # Example: Rename field
    # frappe.reload_doc("module", "doctype", "doctype_name")
    # frappe.db.sql("""
    #     ALTER TABLE `tabDocType Name`
    #     CHANGE COLUMN `old_field` `new_field` VARCHAR(140)
    # """)
    
    frappe.db.commit()
'''
            
            migration_file = f"migrate_{timestamp}.py"
            print(f"\n  Save this as: verenigingen/patches/{migration_file}")
            print("  Add to patches.txt: verenigingen.patches.{migration_file}")
            print("\n" + "="*50)
            print(template)
            print("="*50)
            
    def run_checks(self):
        """Run all migration checks"""
        print("🔄 Checking for migration issues...\n")
        
        all_good = True
        
        all_good &= self.check_patches_txt()
        all_good &= self.check_doctype_changes()
        self.check_field_modifications()
        self.check_custom_scripts()
        
        # Generate report
        print("\n" + "="*50)
        print("📊 MIGRATION CHECK SUMMARY")
        print("="*50)
        
        if self.issues:
            print(f"\n❌ Found {len(self.issues)} issues:")
            for issue in self.issues:
                print(f"  - {issue}")
                
            self.generate_migration_template()
            
            print("\n⚠️  DEPLOYMENT WARNING: Uncommitted migrations detected!")
            print("Please commit all changes or create necessary migrations.")
            sys.exit(1)
        else:
            print("\n✅ No migration issues found!")
            print("All database changes are properly tracked.")
            sys.exit(0)


if __name__ == "__main__":
    checker = MigrationChecker()
    checker.run_checks()