#!/usr/bin/env python3
"""
Validator Improvements Module
============================

Addresses critical false positive issues in the validation orchestrator by implementing
targeted fixes for the most common misclassification patterns.

Key Issues Addressed:
1. SQL query result objects treated as DocType instances
2. Incomplete select field option reporting
3. Context-unaware hasattr() defensive programming detection
4. Standard Frappe field misclassification (enabled, disabled, etc.)

This module provides enhancement patches to the existing validators rather than
rewriting them entirely, maintaining backward compatibility while improving accuracy.
"""

import ast
import re
from typing import Dict, List, Set, Optional, Tuple, Any, Union
from pathlib import Path
import json


class FalsePositiveFilter:
    """Filters out common false positive patterns from validation results"""
    
    def __init__(self):
        # SQL result patterns that are commonly misidentified
        self.sql_result_patterns = [
            r'frappe\.db\.sql\(',
            r'as_dict=True',
            r'\.count\s*,',
            r'COUNT\(\*\)\s+as\s+total',
            r'SUM\(',
            r'SELECT.*as\s+\w+'
        ]
        
        # Standard Frappe DocType fields that exist on most core DocTypes
        self.standard_frappe_fields = {
            'Email Template': ['enabled', 'disabled', 'subject', 'response'],
            'User': ['enabled', 'disabled', 'full_name', 'email'],
            'Role': ['enabled', 'disabled', 'role_name'],
            'DocType': ['enabled', 'disabled', 'module', 'app'],
        }
        
        # Defensive programming patterns
        self.defensive_patterns = [
            r'hasattr\([^,]+,\s*["\'][\w_]+["\']\)',
            r'getattr\([^,]+,\s*["\'][\w_]+["\']',
            r'if\s+\w+\.\w+:',  # Simple existence checks
        ]
    
    def is_sql_result_context(self, line_content: str, broader_context: List[str]) -> bool:
        """Check if the field access is in SQL result context"""
        # Join broader context into single string for pattern matching
        context_text = '\n'.join(broader_context)
        
        # Check for SQL patterns
        for pattern in self.sql_result_patterns:
            if re.search(pattern, context_text, re.IGNORECASE):
                return True
        
        # Check for variable assignment with SQL
        sql_indicators = ['frappe.db.sql', 'as_dict=True', '_sql(', 'frappe.db.get_all']
        for indicator in sql_indicators:
            if indicator in context_text:
                return True
                
        return False
    
    def is_defensive_programming(self, line_content: str, broader_context: List[str]) -> bool:
        """Check if field access is within defensive programming pattern"""
        context_text = '\n'.join(broader_context + [line_content])
        
        for pattern in self.defensive_patterns:
            if re.search(pattern, context_text):
                return True
                
        return False
    
    def is_standard_field_false_positive(self, doctype: str, field_name: str) -> bool:
        """Check if this is a known standard field incorrectly flagged"""
        if doctype in self.standard_frappe_fields:
            return field_name in self.standard_frappe_fields[doctype]
        
        # Common standard fields across many DocTypes
        common_standard_fields = [
            'enabled', 'disabled', 'name', 'creation', 'modified', 'modified_by', 
            'owner', 'docstatus', 'idx', 'title', 'status'
        ]
        
        return field_name in common_standard_fields


class SelectFieldValidatorEnhancement:
    """Enhancements for select field validation accuracy"""
    
    def __init__(self):
        # Known valid status mappings that validators might miss
        self.status_corrections = {
            'Membership': ['Draft', 'Active', 'Pending', 'Inactive', 'Expired', 'Cancelled'],
            'Member': ['Pending', 'Active', 'Rejected', 'Expired', 'Suspended', 'Banned', 'Deceased', 'Terminated'],
            'Volunteer': ['New', 'Onboarding', 'Active', 'Inactive', 'Retired'],
            'Team Member': ['Active', 'Inactive', 'Completed', 'On Leave'],
            'Chapter Member': ['Active', 'Inactive', 'Pending'],
            'SEPA Mandate': ['Draft', 'Active', 'Inactive', 'Expired', 'Cancelled'],
        }
    
    def get_correct_options(self, doctype: str, field_name: str) -> Optional[List[str]]:
        """Get corrected select field options"""
        if field_name == 'status' and doctype in self.status_corrections:
            return self.status_corrections[doctype]
        return None
    
    def validate_select_value(self, doctype: str, field_name: str, value: str) -> bool:
        """Validate if a select field value is actually valid"""
        correct_options = self.get_correct_options(doctype, field_name)
        if correct_options:
            return value in correct_options
        return None  # Unknown - let original validator decide


class ValidationResultEnhancer:
    """Enhances validation results by filtering false positives"""
    
    def __init__(self):
        self.false_positive_filter = FalsePositiveFilter()
        self.select_enhancer = SelectFieldValidatorEnhancement()
    
    def filter_field_reference_issues(self, issues: List[Dict]) -> List[Dict]:
        """Filter out false positive field reference issues"""
        filtered_issues = []
        
        for issue in issues:
            file_path = issue.get('file_path', '')
            line_number = issue.get('line_number', 0)
            context = issue.get('context', '')
            field_name = issue.get('field_name', '')
            doctype = issue.get('doctype', '')
            
            # Read file context for analysis
            try:
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                    
                # Get broader context around the issue
                start = max(0, line_number - 5)
                end = min(len(lines), line_number + 5)
                broader_context = [line.strip() for line in lines[start:end]]
                line_content = lines[line_number - 1].strip() if line_number <= len(lines) else ''
                
                # Apply false positive filters
                if self.false_positive_filter.is_sql_result_context(line_content, broader_context):
                    continue  # Skip SQL result false positives
                    
                if self.false_positive_filter.is_defensive_programming(line_content, broader_context):
                    continue  # Skip defensive programming false positives
                    
                if self.false_positive_filter.is_standard_field_false_positive(doctype, field_name):
                    continue  # Skip standard field false positives
                
            except Exception:
                pass  # If we can't read context, include the issue
            
            # Issue passed all filters - include it
            filtered_issues.append(issue)
        
        return filtered_issues
    
    def filter_select_field_issues(self, issues: List[Dict]) -> List[Dict]:
        """Filter out false positive select field issues"""
        filtered_issues = []
        
        for issue in issues:
            doctype = issue.get('doctype', '')
            field_name = issue.get('field_name', '')
            invalid_value = issue.get('invalid_value', '')
            
            # Check if this is actually a valid value
            is_valid = self.select_enhancer.validate_select_value(doctype, field_name, invalid_value)
            
            if is_valid is True:
                continue  # Skip - value is actually valid
            elif is_valid is None:
                # Unknown - let original validation stand
                filtered_issues.append(issue)
            else:
                # Confirmed invalid
                filtered_issues.append(issue)
        
        return filtered_issues
    
    def enhance_validation_results(self, results: Dict) -> Dict:
        """Enhance overall validation results by filtering false positives"""
        enhanced_results = results.copy()
        
        # Filter field reference issues
        if 'field_reference_issues' in enhanced_results:
            enhanced_results['field_reference_issues'] = self.filter_field_reference_issues(
                results['field_reference_issues']
            )
        
        # Filter select field issues
        if 'select_field_issues' in enhanced_results:
            enhanced_results['select_field_issues'] = self.filter_select_field_issues(
                results['select_field_issues']
            )
        
        # Update totals
        total_filtered = (
            len(enhanced_results.get('field_reference_issues', [])) +
            len(enhanced_results.get('select_field_issues', []))
        )
        
        original_total = (
            len(results.get('field_reference_issues', [])) +
            len(results.get('select_field_issues', []))
        )
        
        filtered_count = original_total - total_filtered
        
        enhanced_results['filtering_summary'] = {
            'original_issues': original_total,
            'filtered_out': filtered_count,
            'remaining_issues': total_filtered,
            'false_positive_rate': f"{(filtered_count/original_total*100):.1f}%" if original_total > 0 else "0%"
        }
        
        return enhanced_results


def main():
    """Demo of validation enhancement"""
    enhancer = ValidationResultEnhancer()
    
    # Example usage
    print("🔧 Validation Enhancement Module Ready")
    print("✅ False positive filtering implemented")
    print("✅ Select field validation corrections added")
    print("✅ SQL result context detection active")
    print("✅ Defensive programming pattern recognition enabled")


if __name__ == "__main__":
    main()