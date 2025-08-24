#!/usr/bin/env python3
"""
Precise Field Reference Scanner

Focused scanner to identify actual DocType field access patterns for problematic 
custom fields. This reduces false positives by focusing on specific field access 
patterns rather than generic string matching.

Author: Claude Code Assistant  
Date: 2025-08-24
"""

import re
import json
from pathlib import Path
from collections import defaultdict

class PreciseFieldScanner:
    """Precisely scans for DocType field access patterns"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.results = defaultdict(list)
        
        # The 19 problematic fields with their DocTypes
        self.target_fields = {
            'eboekhouden_grootboek_nummer': ['Account'],
            'eboekhouden_relation_code': ['Customer', 'Supplier', 'Journal Entry'], 
            'member': ['Customer', 'Sales Invoice'],
            'eboekhouden_invoice_number': ['Journal Entry', 'Purchase Invoice', 'Sales Invoice'],
            'eboekhouden_main_ledger_id': ['Journal Entry'],
            'eboekhouden_mutation_nr': ['Journal Entry', 'Payment Entry', 'Purchase Invoice', 'Sales Invoice'],
            'eboekhouden_mutation_type': ['Journal Entry', 'Payment Entry'],
            'eboekhouden_section': ['Journal Entry'],
            'is_membership_invoice': ['Sales Invoice'],
            'membership': ['Sales Invoice']
        }
        
    def scan_for_field_access(self, fieldname: str) -> dict:
        """Scan for specific field access patterns"""
        print(f"\n🔍 Scanning for field: {fieldname}")
        
        patterns = {
            # Python patterns for actual field access
            'python_attr_access': rf'\.{fieldname}\b(?!\w)',  # doc.member but not doc.member_id
            'python_get_method': rf'\.get\(["\'{fieldname}["\']\)',  # doc.get("member")
            'python_set_method': rf'\.set\(["\'{fieldname}["\']\s*,',  # doc.set("member", value)
            'python_dict_key': rf'["\'{fieldname}["\']\s*:',  # {"member": value}
            'python_filter': rf'filters\s*=.*["\'{fieldname}["\']\s*:',  # filters={"member": ...}
            
            # JavaScript patterns for actual field access
            'js_doc_access': rf'\.doc\.{fieldname}\b',  # frm.doc.member
            'js_set_value': rf'set_value\(["\'{fieldname}["\']\s*,',  # frm.set_value("member", value)
            'js_get_value': rf'get_value\(["\'{fieldname}["\']\)',  # frm.get_value("member")
            
            # SQL patterns
            'sql_column': rf'`{fieldname}`',  # `member` in SQL
            'sql_dot_notation': rf'\.{fieldname}\s*=',  # table.member =
        }
        
        results = {pattern_name: [] for pattern_name in patterns}
        
        # Scan Python files
        for py_file in self.app_path.rglob('*.py'):
            if 'node_modules' in str(py_file) or '__pycache__' in str(py_file):
                continue
                
            try:
                content = py_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                
                for line_num, line in enumerate(lines, 1):
                    for pattern_name, pattern in patterns.items():
                        if pattern_name.startswith('python_') or pattern_name.startswith('sql_'):
                            matches = re.finditer(pattern, line, re.IGNORECASE)
                            for match in matches:
                                results[pattern_name].append({
                                    'file': str(py_file.relative_to(self.app_path)),
                                    'line': line_num,
                                    'content': line.strip(),
                                    'match': match.group(0)
                                })
                                
            except Exception as e:
                continue
        
        # Scan JavaScript files  
        for js_file in self.app_path.rglob('*.js'):
            if 'node_modules' in str(js_file):
                continue
                
            try:
                content = js_file.read_text(encoding='utf-8')
                lines = content.split('\n')
                
                for line_num, line in enumerate(lines, 1):
                    for pattern_name, pattern in patterns.items():
                        if pattern_name.startswith('js_'):
                            matches = re.finditer(pattern, line, re.IGNORECASE)
                            for match in matches:
                                results[pattern_name].append({
                                    'file': str(js_file.relative_to(self.app_path)),
                                    'line': line_num, 
                                    'content': line.strip(),
                                    'match': match.group(0)
                                })
                                
            except Exception as e:
                continue
        
        # Calculate totals
        total_refs = sum(len(refs) for refs in results.values())
        unique_files = len(set(ref['file'] for refs in results.values() for ref in refs))
        
        return {
            'fieldname': fieldname,
            'total_references': total_refs,
            'unique_files': unique_files,
            'patterns': results
        }
    
    def scan_all_target_fields(self):
        """Scan all 19 target fields"""
        print("🎯 Precise Field Reference Scanner - Starting Analysis")
        print("=" * 60)
        
        all_results = {}
        
        for fieldname in self.target_fields.keys():
            result = self.scan_for_field_access(fieldname)
            all_results[fieldname] = result
            
            print(f"  {fieldname}: {result['total_references']} refs across {result['unique_files']} files")
        
        return all_results
    
    def generate_risk_assessment(self, results):
        """Generate risk assessment based on precise counts"""
        risk_levels = {}
        
        for fieldname, data in results.items():
            ref_count = data['total_references'] 
            
            if ref_count > 50:
                risk = 'EXTREME'
            elif ref_count > 15:
                risk = 'HIGH'
            elif ref_count > 5:
                risk = 'MEDIUM'
            else:
                risk = 'LOW'
                
            risk_levels[fieldname] = {
                'risk_level': risk,
                'reference_count': ref_count,
                'files_affected': data['unique_files']
            }
            
        return risk_levels
    
    def save_detailed_report(self, results, risk_assessment, filename):
        """Save detailed report"""
        report = {
            'scan_type': 'precise_field_access',
            'total_fields_scanned': len(results),
            'risk_assessment': risk_assessment,
            'detailed_results': results
        }
        
        output_path = self.app_path / filename
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            
        print(f"📊 Detailed report saved to: {output_path}")

def main():
    """Main execution"""
    scanner = PreciseFieldScanner("/home/frappe/frappe-bench/apps/verenigingen")
    
    # Run precise scan
    results = scanner.scan_all_target_fields()
    risk_assessment = scanner.generate_risk_assessment(results)
    
    print("\n📊 PRECISE ANALYSIS COMPLETE")
    print("=" * 60)
    
    print("\n🎯 RISK BREAKDOWN (Precise Field Access Only):")
    sorted_risks = sorted(risk_assessment.items(), key=lambda x: x[1]['reference_count'], reverse=True)
    
    for fieldname, risk_info in sorted_risks:
        print(f"  {fieldname}: {risk_info['risk_level']} ({risk_info['reference_count']} precise refs, {risk_info['files_affected']} files)")
    
    # Save detailed report
    scanner.save_detailed_report(results, risk_assessment, 'precise_field_analysis.json')
    
    # Identify safest fields to start with
    print(f"\n🚀 RECOMMENDED STARTING FIELDS (LOW/MEDIUM risk):")
    safe_fields = [(name, info) for name, info in sorted_risks if info['risk_level'] in ['LOW', 'MEDIUM']]
    
    for fieldname, risk_info in safe_fields:
        print(f"  ✅ {fieldname}: {risk_info['reference_count']} refs - SAFE TO PROCEED")
    
    if safe_fields:
        safest_field = safe_fields[-1][0]  # Field with lowest refs
        print(f"\n🎯 RECOMMENDED FIRST TARGET: {safest_field}")
    
    print(f"\n❌ HIGH/EXTREME RISK FIELDS (avoid for now):")
    dangerous_fields = [(name, info) for name, info in sorted_risks if info['risk_level'] in ['HIGH', 'EXTREME']]
    for fieldname, risk_info in dangerous_fields[:5]:  # Top 5 most dangerous
        print(f"  💀 {fieldname}: {risk_info['reference_count']} refs - TOO RISKY")

if __name__ == "__main__":
    main()