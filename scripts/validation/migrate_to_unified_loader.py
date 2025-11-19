#!/usr/bin/env python3
"""
Migration Script for Unified DocType Loader
============================================

This script helps migrate validation tools to use the unified DocType loader.

Usage:
    python migrate_to_unified_loader.py

The script will:
1. Scan all validation tools for individual DocType loading methods
2. Report which tools need migration
3. Optionally update the tools automatically
"""

import re
from pathlib import Path
from typing import Dict, List, Set, Tuple


class ValidationToolMigrator:
    """Helps migrate validation tools to unified DocType loader"""
    
    def __init__(self, validation_dir: str):
        self.validation_dir = Path(validation_dir)
        self.results = {
            'already_using_unified': [],
            'needs_migration': [],
            'complex_cases': [],
            'errors': []
        }
    
    def scan_all_validators(self) -> Dict[str, List[str]]:
        """Scan all Python validation files for DocType loading patterns"""
        print("🔍 Scanning validation tools for DocType loading patterns...")
        
        for py_file in self.validation_dir.glob("*.py"):
            if py_file.name.startswith("__"):
                continue
                
            try:
                self._analyze_file(py_file)
            except Exception as e:
                self.results['errors'].append(f"{py_file.name}: {e}")
        
        return self.results
    
    def _analyze_file(self, py_file: Path):
        """Analyze a single Python file for DocType loading patterns"""
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.results['errors'].append(f"{py_file.name}: Cannot read file - {e}")
            return
        
        file_name = py_file.name
        
        # Check if already using unified loader
        if 'from doctype_loader import' in content:
            self.results['already_using_unified'].append(file_name)
            return
        
        # Check for individual DocType loading patterns
        loading_patterns = [
            r'def load.*doctype.*\(',
            r'def.*load.*doctype.*\(',
            r'\.rglob\(.*doctype.*\.json',
            r'for.*doctype.*in.*json',
            r'json\.load.*doctype',
            r'doctype.*fields.*set\(\)'
        ]
        
        found_patterns = []
        for pattern in loading_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                found_patterns.append(pattern)
        
        if found_patterns:
            # Check complexity
            complexity_indicators = [
                'ast.parse',
                'custom_field',
                'child_table',
                'multiple apps',
                'frappe.get_meta'
            ]
            
            complexity_found = [ind for ind in complexity_indicators if ind in content.lower()]
            
            if len(complexity_found) > 2 or len(found_patterns) > 3:
                self.results['complex_cases'].append({
                    'file': file_name,
                    'patterns': found_patterns,
                    'complexity': complexity_found
                })
            else:
                self.results['needs_migration'].append({
                    'file': file_name,
                    'patterns': found_patterns
                })
    
    def print_report(self):
        """Print migration analysis report"""
        print("\n" + "="*60)
        print("UNIFIED DOCTYPE LOADER MIGRATION REPORT")
        print("="*60)
        
        print(f"\n✅ Already using unified loader ({len(self.results['already_using_unified'])}):")
        for file_name in self.results['already_using_unified']:
            print(f"   - {file_name}")
        
        print(f"\n🔄 Simple migration needed ({len(self.results['needs_migration'])}):")
        for item in self.results['needs_migration']:
            print(f"   - {item['file']} ({len(item['patterns'])} patterns)")
        
        print(f"\n⚠️  Complex cases need manual review ({len(self.results['complex_cases'])}):")
        for item in self.results['complex_cases']:
            print(f"   - {item['file']} ({len(item['patterns'])} patterns, complexity: {item['complexity']})")
        
        if self.results['errors']:
            print(f"\n❌ Errors ({len(self.results['errors'])}):")
            for error in self.results['errors']:
                print(f"   - {error}")
        
        # Summary
        total_files = (len(self.results['already_using_unified']) + 
                      len(self.results['needs_migration']) + 
                      len(self.results['complex_cases']))
        
        print(f"\n📊 SUMMARY:")
        print(f"   Total validation files analyzed: {total_files}")
        print(f"   Already migrated: {len(self.results['already_using_unified'])}")
        print(f"   Ready for simple migration: {len(self.results['needs_migration'])}")
        print(f"   Need manual review: {len(self.results['complex_cases'])}")
        
        if len(self.results['already_using_unified']) > 0:
            migration_percentage = (len(self.results['already_using_unified']) / total_files) * 100
            print(f"   Migration progress: {migration_percentage:.1f}%")
    
    def generate_migration_code(self, file_name: str) -> str:
        """Generate migration code for a specific file"""
        return f'''
# Add this import at the top of {file_name}:
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from doctype_loader import load_doctypes_simple

# Replace your load_doctypes method with:
def load_doctypes(self) -> Dict[str, Set[str]]:
    """Load DocTypes using unified loader"""
    return load_doctypes_simple(str(self.app_path), verbose=False)

# For detailed DocType information, use:
from doctype_loader import load_doctypes_detailed

def load_doctypes_detailed(self) -> Dict[str, Dict]:
    """Load detailed DocType information using unified loader"""
    return load_doctypes_detailed(str(self.app_path), verbose=False)
'''


def main():
    """Main migration analysis"""
    validation_dir = Path(__file__).parent
    
    migrator = ValidationToolMigrator(str(validation_dir))
    results = migrator.scan_all_validators()
    migrator.print_report()
    
    # Provide specific migration guidance
    if results['needs_migration']:
        print("\n" + "="*60)
        print("MIGRATION GUIDANCE")
        print("="*60)
        print("\nFor simple migrations, replace individual DocType loading with:")
        print(migrator.generate_migration_code("<your_file>"))
    
    return 0


if __name__ == "__main__":
    exit(main())