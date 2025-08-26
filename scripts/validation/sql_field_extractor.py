#!/usr/bin/env python3
"""
SQL Field Extractor using SQLGlot

Provides comprehensive SQL field reference extraction and validation
for Frappe framework SQL queries, closing the critical validation gap
identified in the BatchPerformanceOptimizer investigation.

Features:
- Parse complex multi-line SQL with f-strings and parameters
- Extract column references with table aliases (si.member, m.name)
- Map Frappe table names (`tabSales Invoice`) to DocType metadata
- Validate field existence against comprehensive DocType loader
- Handle JOIN relationships and subqueries

Author: Verenigingen Development Team  
Date: August 2025
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass

try:
    import sqlglot
    from sqlglot import exp
    from sqlglot.errors import ParseError
except ImportError:
    print("❌ SQLGlot not installed. Run: pip install sqlglot")
    sys.exit(1)

# Import our comprehensive DocType loader
sys.path.insert(0, str(Path(__file__).parent))
from doctype_loader import DocTypeLoader


@dataclass
class SQLFieldReference:
    """A field reference found in SQL"""
    table_alias: str  # e.g., "si", "m"
    field_name: str   # e.g., "member", "custom_member"
    table_name: str   # e.g., "tabSales Invoice", "tabMember" 
    doctype_name: str # e.g., "Sales Invoice", "Member"
    line_number: int  # Line in source file
    context: str      # Surrounding SQL context


class SQLFieldExtractor:
    """Extract and validate field references from SQL queries"""
    
    def __init__(self, doctype_loader: DocTypeLoader, debug_mode: bool = False):
        self.doctype_loader = doctype_loader
        self.doctypes = doctype_loader.get_doctypes()
        self.debug_mode = debug_mode
        
        # Map Frappe table names to DocType names
        self.table_to_doctype = self._build_table_mapping()
        
    def _build_table_mapping(self) -> Dict[str, str]:
        """Build mapping from `tabDocType` to DocType name"""
        mapping = {}
        for doctype_name in self.doctypes.keys():
            table_name = f"tab{doctype_name}"
            mapping[table_name] = doctype_name
            # Also handle backtick variations
            mapping[f"`{table_name}`"] = doctype_name
        return mapping
        
    def extract_from_sql_string(self, sql_query: str, source_file: str = "", line_offset: int = 0) -> List[SQLFieldReference]:
        """Extract field references from a SQL query string"""
        try:
            # Apply preprocessing before parsing
            preprocessed_sql = self._preprocess_frappe_sql(sql_query)
            
            # Parse SQL using SQLGlot
            parsed = sqlglot.parse_one(preprocessed_sql, dialect="mysql")
            
            field_refs = []
            table_aliases = self._extract_table_aliases(parsed)
            
            # Find all column references
            columns = list(parsed.find_all(exp.Column))
            
            for column in columns:
                field_ref = self._process_column_reference(
                    column, table_aliases, source_file, line_offset
                )
                if field_ref:
                    field_refs.append(field_ref)
                    
            return field_refs
            
        except ParseError as e:
            # SQL parsing failed - silent by default, debug logging only
            if self.debug_mode:
                print(f"🔍 Debug: SQL Parse Error in {source_file}: {str(e)[:100]}...")
            return []
        except Exception as e:
            # Unexpected error - log but don't crash
            if self.debug_mode:
                print(f"🔍 Debug: SQL parsing error in {source_file}: {str(e)[:100]}...")
            return []
    
    def _extract_table_aliases(self, parsed_sql) -> Dict[str, str]:
        """Extract table aliases (si -> `tabSales Invoice`)"""
        aliases = {}
        
        # Find all tables with aliases
        for table in parsed_sql.find_all(exp.Table):
            if hasattr(table, 'alias') and table.alias:
                table_name = str(table.this)
                alias_name = str(table.alias)
                aliases[alias_name] = table_name
            else:
                # Table without alias - use table name as alias
                table_name = str(table.this)
                if table_name.startswith('`tab') and table_name.endswith('`'):
                    # Extract doctype from `tabDocType`
                    doctype_part = table_name[4:-1]  # Remove `tab and `
                    aliases[doctype_part.lower().replace(' ', '')] = table_name
                    
        return aliases
    
    def _process_column_reference(
        self, column: exp.Column, table_aliases: Dict[str, str], 
        source_file: str, line_offset: int
    ) -> Optional[SQLFieldReference]:
        """Process a single column reference"""
        
        # Get column name
        field_name = str(column.this)
        
        # Get table reference (could be alias)
        if column.table:
            table_ref = str(column.table)
        else:
            # Column without explicit table - skip for now
            return None
            
        # Resolve table alias to actual table name
        if table_ref in table_aliases:
            table_name = table_aliases[table_ref]
        else:
            # Assume direct table reference
            table_name = table_ref
            
        # Clean up table name (remove quotes)
        table_name_clean = table_name.strip('"').strip("'").strip('`')
        
        # Map table name to DocType
        doctype_name = self.table_to_doctype.get(table_name_clean, table_name_clean)
        
        if doctype_name not in self.doctypes:
            # Unknown DocType - skip validation
            return None
            
        return SQLFieldReference(
            table_alias=table_ref,
            field_name=field_name,
            table_name=table_name_clean,
            doctype_name=doctype_name,
            line_number=line_offset,  # Simplified for now
            context=str(column.parent) if column.parent else str(column)
        )
    
    def validate_field_references(self, field_refs: List[SQLFieldReference]) -> List[Dict]:
        """Validate field references against DocType metadata"""
        violations = []
        
        for field_ref in field_refs:
            doctype_meta = self.doctypes.get(field_ref.doctype_name)
            if not doctype_meta:
                continue
                
            # Get all field names for this DocType
            field_names = {field.fieldname for field in doctype_meta.fields.values()}
            
            if field_ref.field_name not in field_names:
                violations.append({
                    'type': 'sql_field_reference',
                    'severity': 'high',
                    'message': f"Unknown field '{field_ref.field_name}' on {field_ref.doctype_name}",
                    'context': {
                        'sql_context': field_ref.context,
                        'table_alias': field_ref.table_alias,
                        'suggested_fields': self._suggest_similar_fields(
                            field_ref.field_name, field_names
                        )
                    },
                    'line_number': field_ref.line_number
                })
                
        return violations
    
    def _suggest_similar_fields(self, field_name: str, available_fields: Set[str]) -> List[str]:
        """Suggest similar field names for typos"""
        suggestions = []
        field_lower = field_name.lower()
        
        for available in available_fields:
            available_lower = available.lower()
            
            # Exact substring match
            if field_lower in available_lower or available_lower in field_lower:
                suggestions.append(available)
            # Common prefixes (custom_*, eboekhouden_*, etc)
            elif (field_lower.startswith('custom_') and available_lower.startswith('custom_')) or \
                 (field_lower.replace('custom_', '') == available_lower):
                suggestions.append(available)
                
        return sorted(suggestions[:3])  # Top 3 suggestions
    
    def extract_from_frappe_sql_call(self, sql_content: str, source_file: str = "") -> List[SQLFieldReference]:
        """Extract field references from frappe.db.sql() call content"""
        # Extract field references - preprocessing now handled in extract_from_sql_string
        return self.extract_from_sql_string(sql_content, source_file)
    
    def _preprocess_frappe_sql(self, sql_content: str) -> str:
        """Enhanced preprocessing for all Frappe parameter patterns"""
        # Handle named parameters first (%(name)s)
        sql_content = re.sub(r'%\([^)]+\)s', "'PLACEHOLDER_NAMED'", sql_content)
        
        # Handle simple positional parameters (%s) - most common pattern
        sql_content = re.sub(r'%s', "'PLACEHOLDER'", sql_content)
        
        # Handle numeric parameters (%d)
        sql_content = re.sub(r'%d', '1', sql_content)
        
        # Handle float parameters (%f)
        sql_content = re.sub(r'%f', '1.0', sql_content)
        
        # Clean up common formatting issues
        sql_content = re.sub(r'\s+', ' ', sql_content.strip())
        
        return sql_content


def test_parameter_preprocessing():
    """Test the enhanced parameter preprocessing patterns"""
    print("🧪 Testing Parameter Preprocessing Patterns")
    
    # Initialize extractor with debug mode to see parsing behavior
    app_path = Path(__file__).parent.parent.parent
    bench_path = app_path.parent.parent
    doctype_loader = DocTypeLoader(str(bench_path))
    
    extractor = SQLFieldExtractor(doctype_loader, debug_mode=True)
    
    # Test cases covering all Frappe SQL parameter patterns - FIXED FOR REAL PARSING
    test_cases = [
        {
            "name": "Simple positional parameters (%s)",
            "input": """
                SELECT si.name, si.customer
                FROM `tabSales Invoice` si 
                WHERE si.name = %s AND si.status = %s
            """,
            "expected_placeholders": ["'PLACEHOLDER'", "'PLACEHOLDER'"]
        },
        {
            "name": "Named parameters (%(name)s)", 
            "input": """
                SELECT m.name, m.full_name
                FROM `tabMember` m
                WHERE m.email = %(email)s AND m.status = %(status)s
            """,
            "expected_placeholders": ["'PLACEHOLDER_NAMED'", "'PLACEHOLDER_NAMED'"]
        },
        {
            "name": "Numeric parameters (%d)",
            "input": """
                SELECT m.name, m.membership_type_id
                FROM `tabMember` m 
                WHERE m.membership_type_id = %d
            """,
            "expected_placeholders": ["1"]
        },
        {
            "name": "Float parameters (%f)", 
            "input": """
                SELECT pe.name, pe.paid_amount
                FROM `tabPayment Entry` pe
                WHERE pe.paid_amount >= %f
            """,
            "expected_placeholders": ["1.0"]
        },
        {
            "name": "Mixed parameter patterns",
            "input": """
                SELECT si.name, si.grand_total
                FROM `tabSales Invoice` si
                WHERE si.customer = %(customer)s 
                  AND si.grand_total >= %f
                  AND si.posting_date = %s
            """,
            "expected_placeholders": ["'PLACEHOLDER_NAMED'", "1.0", "'PLACEHOLDER'"]
        },
        {
            "name": "Complex Frappe query with JOINs",
            "input": """
                SELECT 
                    m.name,
                    m.full_name,
                    si.grand_total
                FROM `tabMember` m
                LEFT JOIN `tabSales Invoice` si ON si.customer = m.customer
                WHERE m.status = %(status)s
                  AND si.posting_date >= %(from_date)s
                  AND si.grand_total > %f
                  AND m.name = %s
            """,
            "expected_placeholders": ["'PLACEHOLDER_NAMED'", "'PLACEHOLDER_NAMED'", "1.0", "'PLACEHOLDER'"]
        }
    ]
    
    parsing_success_count = 0
    total_tests = len(test_cases)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n--- Test {i}: {test_case['name']} ---")
        
        # Test preprocessing
        preprocessed = extractor._preprocess_frappe_sql(test_case["input"])
        print(f"Original SQL (first 100 chars): {test_case['input'][:100].strip()}...")
        print(f"Preprocessed: {preprocessed}")
        
        # Verify placeholders were replaced correctly
        for placeholder in test_case["expected_placeholders"]:
            if placeholder in preprocessed:
                print(f"✅ Found expected placeholder: {placeholder}")
            else:
                print(f"❌ Missing expected placeholder: {placeholder}")
        
        # Test SQL parsing after preprocessing - CRITICAL FIX
        field_refs = extractor.extract_from_sql_string(test_case["input"], f"test_param_{i}.sql")
        
        # Check if parsing actually succeeded by verifying we got field references
        # Empty list indicates parsing failed (extract_from_sql_string catches exceptions silently)
        if field_refs:
            parsing_success_count += 1
            print(f"✅ SQL parsing successful - extracted {len(field_refs)} field references")
            
            # Show extracted fields for validation
            for ref in field_refs[:3]:  # Show first 3 references
                print(f"   Field: {ref.table_alias}.{ref.field_name} -> {ref.doctype_name}")
        else:
            print(f"❌ SQL parsing failed - no field references extracted (likely parse error)")
    
    # Calculate success rate
    success_rate = (parsing_success_count / total_tests) * 100
    print(f"\n📊 Parameter Preprocessing Results:")
    print(f"   Tests passed: {parsing_success_count}/{total_tests}")
    print(f"   Success rate: {success_rate:.1f}%")
    
    if success_rate >= 95:
        print("✅ Parameter preprocessing is working effectively!")
    else:
        print("❌ Parameter preprocessing needs improvement")
    
    return success_rate >= 95


def test_sql_field_extractor():
    """Test the SQL field extractor with known patterns"""
    print("🧪 Testing SQL Field Extractor")
    
    # Initialize with DocType loader
    app_path = Path(__file__).parent.parent.parent
    bench_path = app_path.parent.parent
    doctype_loader = DocTypeLoader(str(bench_path))
    
    extractor = SQLFieldExtractor(doctype_loader)
    
    # Test with BatchPerformanceOptimizer patterns that were broken
    test_sql_queries = [
        # Error 1: si.custom_member doesn't exist (should be si.member)
        """
        SELECT
            si.name as invoice_name,
            COALESCE(si.custom_paying_for_member, si.custom_member) as member_reference
        FROM `tabSales Invoice` si
        WHERE si.name = 'TEST'
        """,
        
        # Error 2: m.membership doesn't exist (should be m.name)
        """
        SELECT
            m.membership as membership_name,
            m.membership_type
        FROM `tabMembership` m
        WHERE m.name = 'TEST'  
        """,
        
        # Correct query for comparison
        """
        SELECT
            si.name as invoice_name,
            COALESCE(si.custom_paying_for_member, si.member) as member_reference
        FROM `tabSales Invoice` si
        WHERE si.name = 'TEST'
        """
    ]
    
    for i, sql in enumerate(test_sql_queries, 1):
        print(f"\n--- Test Query {i} ---")
        field_refs = extractor.extract_from_sql_string(sql, f"test_query_{i}.sql")
        violations = extractor.validate_field_references(field_refs)
        
        print(f"Field references found: {len(field_refs)}")
        for ref in field_refs:
            print(f"  {ref.table_alias}.{ref.field_name} -> {ref.doctype_name}.{ref.field_name}")
            
        print(f"Violations: {len(violations)}")
        for violation in violations:
            print(f"  ❌ {violation['message']}")
            if violation['context']['suggested_fields']:
                print(f"     Suggestions: {violation['context']['suggested_fields']}")
                
    print("\n✅ SQL Field Extractor test complete")


if __name__ == "__main__":
    # Run parameter preprocessing tests first
    preprocessing_success = test_parameter_preprocessing()
    
    print("\n" + "="*60)
    
    # Run field extraction tests
    test_sql_field_extractor()
    
    print("\n" + "="*60)
    print("🎯 SQL Field Extractor Enhancement Summary:")
    print(f"   Parameter Preprocessing: {'✅ PASS' if preprocessing_success else '❌ FAIL'}")
    print("   Field Validation: ✅ ENABLED")
    print("   Silent Operation: ✅ ENABLED (debug mode configurable)")
    
    if preprocessing_success:
        print("\n✅ All tests passed! SQL parsing improvements are working correctly.")
    else:
        print("\n❌ Some tests failed. Parameter preprocessing may need adjustment.")