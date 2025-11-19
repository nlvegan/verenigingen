#!/usr/bin/env python3
"""
Field Reference Mapper

Comprehensive tool to map all references to custom fields that need to be renamed.
This tool analyzes Python, JavaScript, SQL, JSON, and template files to provide
a complete picture of where field names are used throughout the codebase.

Author: Claude Code Assistant
Date: 2025-08-24
"""

import os
import re
import json
import ast
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict

class FieldReferenceMapper:
    """Maps all references to problematic custom field names"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.problematic_fields = self._load_problematic_fields()
        self.references = defaultdict(list)
        self.file_types = {
            '.py': 'python',
            '.js': 'javascript', 
            '.json': 'json',
            '.html': 'template',
            '.jinja': 'template',
            '.sql': 'sql'
        }
        
    def _load_problematic_fields(self) -> Dict[str, List[str]]:
        """Load the 19 problematic fields from custom_field.json"""
        custom_fields_path = self.app_path / 'verenigingen/fixtures/custom_field.json'
        
        with open(custom_fields_path) as f:
            fields = json.load(f)
            
        # Extract fields that don't start with custom_
        problematic = {}
        for field in fields:
            fieldname = field['fieldname']
            if not fieldname.startswith('custom_'):
                dt = field['dt']
                if dt not in problematic:
                    problematic[dt] = []
                problematic[dt].append(fieldname)
                
        return problematic
    
    def scan_all_files(self) -> Dict:
        """Scan all relevant files for field references"""
        print("🔍 Starting comprehensive field reference scan...")
        
        # Scan different file types
        for root, dirs, files in os.walk(self.app_path / 'verenigingen'):
            # Skip node_modules and other irrelevant directories
            dirs[:] = [d for d in dirs if d not in ['node_modules', '__pycache__', '.git']]
            
            for file in files:
                file_path = Path(root) / file
                file_ext = file_path.suffix
                
                if file_ext in self.file_types:
                    self._scan_file(file_path, self.file_types[file_ext])
                    
        return self._generate_report()
    
    def _scan_file(self, file_path: Path, file_type: str):
        """Scan individual file for field references"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            if file_type == 'python':
                self._scan_python_file(file_path, content)
            elif file_type == 'javascript':
                self._scan_javascript_file(file_path, content)
            elif file_type == 'json':
                self._scan_json_file(file_path, content)
            elif file_type == 'template':
                self._scan_template_file(file_path, content)
            elif file_type == 'sql':
                self._scan_sql_file(file_path, content)
                
        except Exception as e:
            print(f"⚠️  Error scanning {file_path}: {e}")
    
    def _scan_python_file(self, file_path: Path, content: str):
        """Scan Python file for field references"""
        lines = content.split('\n')
        
        for dt, fieldnames in self.problematic_fields.items():
            for fieldname in fieldnames:
                # Pattern 1: doc.fieldname
                pattern1 = rf'\b\w+\.{re.escape(fieldname)}\b'
                # Pattern 2: doc.get("fieldname")  
                pattern2 = rf'\.get\(["\']?{re.escape(fieldname)}["\']?\)'
                # Pattern 3: "fieldname" in dictionaries/filters
                pattern3 = rf'["\']?{re.escape(fieldname)}["\']?\s*:'
                # Pattern 4: SQL-style references
                pattern4 = rf'`?{re.escape(fieldname)}`?\s*='
                
                patterns = [pattern1, pattern2, pattern3, pattern4]
                
                for line_num, line in enumerate(lines, 1):
                    for pattern in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            self.references[f"{dt}.{fieldname}"].append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': line_num,
                                'content': line.strip(),
                                'type': 'python',
                                'pattern': pattern
                            })
    
    def _scan_javascript_file(self, file_path: Path, content: str):
        """Scan JavaScript file for field references"""
        lines = content.split('\n')
        
        for dt, fieldnames in self.problematic_fields.items():
            for fieldname in fieldnames:
                # Pattern 1: frm.doc.fieldname
                pattern1 = rf'\b\w+\.{re.escape(fieldname)}\b'
                # Pattern 2: set_value("fieldname")
                pattern2 = rf'set_value\(["\']?{re.escape(fieldname)}["\']?'
                # Pattern 3: fieldname in object literals
                pattern3 = rf'["\']?{re.escape(fieldname)}["\']?\s*:'
                
                patterns = [pattern1, pattern2, pattern3]
                
                for line_num, line in enumerate(lines, 1):
                    for pattern in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            self.references[f"{dt}.{fieldname}"].append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': line_num,
                                'content': line.strip(),
                                'type': 'javascript',
                                'pattern': pattern
                            })
    
    def _scan_json_file(self, file_path: Path, content: str):
        """Scan JSON file for field references"""
        for dt, fieldnames in self.problematic_fields.items():
            for fieldname in fieldnames:
                if f'"{fieldname}"' in content:
                    # Find line numbers for JSON references
                    lines = content.split('\n')
                    for line_num, line in enumerate(lines, 1):
                        if f'"{fieldname}"' in line:
                            self.references[f"{dt}.{fieldname}"].append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': line_num,
                                'content': line.strip(),
                                'type': 'json',
                                'pattern': f'"{fieldname}"'
                            })
    
    def _scan_template_file(self, file_path: Path, content: str):
        """Scan template file for field references"""
        for dt, fieldnames in self.problematic_fields.items():
            for fieldname in fieldnames:
                # Jinja/template patterns  
                pattern1 = r'\{\{\s*\w*\.?' + re.escape(fieldname) + r'\s*\}\}'
                pattern2 = r'\{%.*' + re.escape(fieldname) + r'.*%\}'
                
                patterns = [pattern1, pattern2]
                lines = content.split('\n')
                
                for line_num, line in enumerate(lines, 1):
                    for pattern in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            self.references[f"{dt}.{fieldname}"].append({
                                'file': str(file_path.relative_to(self.app_path)),
                                'line': line_num,
                                'content': line.strip(),
                                'type': 'template',
                                'pattern': pattern
                            })
    
    def _scan_sql_file(self, file_path: Path, content: str):
        """Scan SQL file for field references"""
        for dt, fieldnames in self.problematic_fields.items():
            for fieldname in fieldnames:
                # SQL patterns
                pattern = rf'`?{re.escape(fieldname)}`?'
                lines = content.split('\n')
                
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        self.references[f"{dt}.{fieldname}"].append({
                            'file': str(file_path.relative_to(self.app_path)),
                            'line': line_num,
                            'content': line.strip(),
                            'type': 'sql',
                            'pattern': pattern
                        })
    
    def _generate_report(self) -> Dict:
        """Generate comprehensive reference report"""
        report = {
            'summary': {
                'total_fields': len([field for fields in self.problematic_fields.values() for field in fields]),
                'total_references': sum(len(refs) for refs in self.references.values()),
                'files_affected': len(set(ref['file'] for refs in self.references.values() for ref in refs))
            },
            'field_breakdown': {},
            'risk_assessment': {}
        }
        
        # Generate field breakdown
        for field_key, refs in self.references.items():
            report['field_breakdown'][field_key] = {
                'reference_count': len(refs),
                'files_affected': len(set(ref['file'] for ref in refs)),
                'file_types': list(set(ref['type'] for ref in refs)),
                'references': refs[:10]  # First 10 references for preview
            }
            
        # Risk assessment
        for field_key, refs in self.references.items():
            ref_count = len(refs)
            if ref_count > 100:
                risk = 'EXTREME'
            elif ref_count > 20:
                risk = 'HIGH'  
            elif ref_count > 5:
                risk = 'MEDIUM'
            else:
                risk = 'LOW'
                
            report['risk_assessment'][field_key] = {
                'risk_level': risk,
                'reference_count': ref_count,
                'justification': f"{ref_count} references across {len(set(ref['file'] for ref in refs))} files"
            }
            
        return report
    
    def save_report(self, report: Dict, output_file: str):
        """Save detailed report to file"""
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"📊 Report saved to: {output_file}")

def main():
    """Main execution"""
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    
    print("🎯 Field Reference Mapper - Starting Analysis")
    print("=" * 60)
    
    mapper = FieldReferenceMapper(app_path)
    
    print("📋 Problematic fields identified:")
    for dt, fields in mapper.problematic_fields.items():
        print(f"  {dt}: {', '.join(fields)}")
    
    print(f"\n🔍 Scanning {app_path} recursively...")
    report = mapper.scan_all_files()
    
    # Print summary
    print("\n📊 ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Total fields analyzed: {report['summary']['total_fields']}")
    print(f"Total references found: {report['summary']['total_references']}")
    print(f"Files affected: {report['summary']['files_affected']}")
    
    print("\n🎯 RISK BREAKDOWN:")
    for field, risk_info in report['risk_assessment'].items():
        print(f"  {field}: {risk_info['risk_level']} ({risk_info['reference_count']} refs)")
    
    # Save detailed report
    output_file = "/home/frappe/frappe-bench/apps/verenigingen/field_reference_analysis.json"
    mapper.save_report(report, output_file)
    
    print(f"\n✅ Complete analysis saved to: {output_file}")

if __name__ == "__main__":
    main()