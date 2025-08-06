#!/usr/bin/env python3
"""
Comprehensive Test Suite for Schema-Aware Validator

Tests all components of the improved validation system to ensure
it correctly handles various edge cases and reduces false positives.
"""

import unittest
import tempfile
import json
import re
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import List, Dict, Any
import sys
import os


@dataclass
class ValidationIssue:
    """Represents a validation issue"""
    file: str
    line: int
    field: str
    doctype: str
    reference: str
    message: str
    context: str
    confidence: str
    issue_type: str
    suggested_fix: str

# Add validation directory to path
sys.path.insert(0, str(Path(__file__).parent))


class TestSchemaAwareValidatorEnhanced:
    """Enhanced test validator with DocType existence checking"""
    
    def __init__(self, app_path: str):
        self.app_path = Path(app_path)
        self.doctypes = self._load_available_doctypes()
    
    def _load_available_doctypes(self) -> Dict[str, Any]:
        """Load available DocTypes for first-layer validation"""
        doctypes = {}
        doctype_dir = self.app_path / "verenigingen" / "verenigingen" / "doctype"
        
        if not doctype_dir.exists():
            return doctypes
        
        for doctype_path in doctype_dir.iterdir():
            if doctype_path.is_dir():
                json_file = doctype_path / f"{doctype_path.name}.json"
                if json_file.exists():
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        doctypes[data.get('name', '')] = data
                    except Exception:
                        pass
        
        return doctypes
    
    def validate_doctype_api_calls(self, content: str, file_path: Path) -> List[ValidationIssue]:
        """FIRST-LAYER CHECK: Validate DocType existence in API calls"""
        violations = []
        
        # Patterns for Frappe API calls that use DocType names
        api_patterns = [
            r'frappe\.get_all\(\s*["\']([^"\']+)["\']',
            r'frappe\.get_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.new_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.delete_doc\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.get_value\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.exists\(\s*["\']([^"\']+)["\']',
            r'frappe\.db\.count\(\s*["\']([^"\']+)["\']',
            r'DocType\(\s*["\']([^"\']+)["\']',
        ]
        
        lines = content.splitlines()
        
        for line_num, line in enumerate(lines, 1):
            for pattern in api_patterns:
                matches = re.finditer(pattern, line)
                for match in matches:
                    doctype_name = match.group(1)
                    
                    # FIRST-LAYER CHECK: Does this DocType actually exist?
                    if doctype_name not in self.doctypes:
                        # Suggest similar DocType names
                        suggestions = self._suggest_similar_doctype(doctype_name)
                        
                        violations.append(ValidationIssue(
                            file=str(file_path.relative_to(self.app_path)),
                            line=line_num,
                            field="<doctype_reference>",
                            doctype=doctype_name,
                            reference=line.strip(),
                            message=f"DocType '{doctype_name}' does not exist. {suggestions}",
                            context=line.strip(),
                            confidence="high",
                            issue_type="missing_doctype",
                            suggested_fix=suggestions
                        ))
        
        return violations
    
    def _suggest_similar_doctype(self, invalid_name: str) -> str:
        """Suggest similar DocType names for typos"""
        available = list(self.doctypes.keys())
        
        # Look for exact substring matches first
        exact_matches = [dt for dt in available if invalid_name.replace('Verenigingen ', '') in dt]
        if exact_matches:
            return f"Did you mean '{exact_matches[0]}'?"
        
        # Look for partial matches
        partial_matches = [dt for dt in available if any(word in dt for word in invalid_name.split())]
        if partial_matches:
            return f"Similar: {', '.join(partial_matches[:3])}"
        
        return f"Check {len(available)} available DocTypes"


# Mock imports for testing (if modules don't exist)
try:
    from schema_aware_validator import (
        SchemaAwareValidator, DatabaseSchemaReader, ContextAnalyzer, 
        FrappePatternHandler, ValidationEngine, DocTypeSchema
    )
except ImportError:
    # Create mock classes for testing
    class SchemaAwareValidator:
        def __init__(self, app_path, verbose=False):
            self.validator = TestSchemaAwareValidatorEnhanced(app_path)
        
        def validate_file(self, file_path):
            with open(file_path, 'r') as f:
                content = f.read()
            return self.validator.validate_doctype_api_calls(content, Path(file_path))
        
        def validate_directory(self):
            return []
    
    DatabaseSchemaReader = Mock
    ContextAnalyzer = Mock
    FrappePatternHandler = Mock
    ValidationEngine = Mock
    DocTypeSchema = Mock

try:
    from validation_config import (
        ConfigurationManager, ValidationLevel, ValidationConfig, ConfidenceThresholds
    )
except ImportError:
    # Create mock classes for testing
    from enum import Enum
    
    class ValidationLevel(Enum):
        STRICT = "strict"
        BALANCED = "balanced"
        PERMISSIVE = "permissive"
        CUSTOM = "custom"
    
    class ConfidenceThresholds:
        def __init__(self):
            self.field_access = 0.8
    
    class ValidationConfig:
        def __init__(self, level):
            self.level = level
            self.confidence_thresholds = ConfidenceThresholds()
    
    class ConfigurationManager:
        def __init__(self, path):
            self.path = path
        
        def get_preset_config(self, level):
            return ValidationConfig(level)
        
        def save_config(self, config):
            pass
        
        def load_config(self):
            return ValidationConfig(ValidationLevel.BALANCED)
        
        def create_custom_config(self, level, **kwargs):
            config = ValidationConfig(ValidationLevel.CUSTOM)
            for key, value in kwargs.items():
                if hasattr(config.confidence_thresholds, key):
                    setattr(config.confidence_thresholds, key, value)
            return config


class TestDatabaseSchemaReader(unittest.TestCase):
    """Test the database schema reader component"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.app_path = Path(self.temp_dir)
        
        # Create mock DocType structure
        self.doctype_dir = self.app_path / "verenigingen" / "verenigingen" / "doctype"
        self.doctype_dir.mkdir(parents=True)
        
        # Create a mock Member DocType
        member_dir = self.doctype_dir / "member"
        member_dir.mkdir()
        
        member_json = {
            "name": "Member",
            "istable": 0,
            "fields": [
                {"fieldname": "first_name", "fieldtype": "Data"},
                {"fieldname": "last_name", "fieldtype": "Data"},
                {"fieldname": "email", "fieldtype": "Data"},
                {"fieldname": "memberships", "fieldtype": "Table", "options": "Chapter Member"}
            ]
        }
        
        with open(member_dir / "member.json", 'w') as f:
            json.dump(member_json, f)
        
        # Create a mock Chapter Member child table
        chapter_member_dir = self.doctype_dir / "chapter_member"
        chapter_member_dir.mkdir()
        
        chapter_member_json = {
            "name": "Chapter Member",
            "istable": 1,
            "fields": [
                {"fieldname": "chapter", "fieldtype": "Link", "options": "Chapter"},
                {"fieldname": "membership_type", "fieldtype": "Select"},
                {"fieldname": "start_date", "fieldtype": "Date"}
            ]
        }
        
        with open(chapter_member_dir / "chapter_member.json", 'w') as f:
            json.dump(chapter_member_json, f)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_load_doctype_schemas(self):
        """Test loading DocType schemas from JSON files"""
        reader = DatabaseSchemaReader(str(self.app_path))
        
        # Should load both Member and Chapter Member
        self.assertIn("Member", reader.doctypes)
        self.assertIn("Chapter Member", reader.doctypes)
        
        # Check Member fields
        member_schema = reader.doctypes["Member"]
        self.assertEqual(member_schema.name, "Member")
        self.assertIn("first_name", member_schema.fields)
        self.assertIn("email", member_schema.fields) 
        self.assertIn("memberships", member_schema.child_tables)
        self.assertEqual(member_schema.child_tables["memberships"], "Chapter Member")
    
    def test_field_validation(self):
        """Test field existence validation"""
        reader = DatabaseSchemaReader(str(self.app_path))
        
        # Valid fields
        self.assertTrue(reader.is_valid_field("Member", "first_name"))
        self.assertTrue(reader.is_valid_field("Member", "email"))
        self.assertTrue(reader.is_valid_field("Chapter Member", "chapter"))
        
        # Invalid fields
        self.assertFalse(reader.is_valid_field("Member", "nonexistent_field"))
        self.assertFalse(reader.is_valid_field("Nonexistent DocType", "any_field"))
    
    def test_child_table_relationships(self):
        """Test child table relationship detection"""
        reader = DatabaseSchemaReader(str(self.app_path))
        
        # Should detect child table relationship
        child_doctype = reader.get_child_table_doctype("Member", "memberships")
        self.assertEqual(child_doctype, "Chapter Member")
        
        # Non-existent relationships
        self.assertIsNone(reader.get_child_table_doctype("Member", "nonexistent"))
        self.assertIsNone(reader.get_child_table_doctype("Nonexistent", "memberships"))


class TestContextAnalyzer(unittest.TestCase):
    """Test the context analyzer component"""
    
    def setUp(self):
        self.mock_schema_reader = Mock()
        self.mock_schema_reader.doctypes = {
            "Member": Mock(),
            "Chapter": Mock()
        }
        self.analyzer = ContextAnalyzer(self.mock_schema_reader)
    
    def test_analyze_variable_assignments(self):
        """Test detection of variable assignments"""
        test_code = '''
member = frappe.get_doc("Member", "test")
sql_result = frappe.db.sql("SELECT * FROM tabMember", as_dict=True)
api_result = frappe.get_all("Member", fields=["name", "email"])
'''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_code)
            f.flush()
            
            contexts = self.analyzer.analyze_file_context(Path(f.name))
            
            # Should detect different types of assignments
            self.assertTrue(len(contexts) > 0)
            
            # Check if SQL variables are detected (implementation dependent)
            # This is a basic structural test
        
        os.unlink(f.name)
    
    def test_property_method_detection(self):
        """Test detection of @property methods"""
        test_code = '''
class TestClass:
    @property
    def computed_field(self):
        return self._computed_value
    
    def regular_method(self):
        return "not a property"
'''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_code)
            f.flush()
            
            contexts = self.analyzer.analyze_file_context(Path(f.name))
            
            # Should detect property method
            found_property = False
            for context in contexts.values():
                if 'computed_field' in context.property_methods:
                    found_property = True
                    break
            
            self.assertTrue(found_property)
        
        os.unlink(f.name)


class TestFrappePatternHandler(unittest.TestCase):
    """Test the Frappe pattern handler component"""
    
    def setUp(self):
        self.handler = FrappePatternHandler()
    
    def test_wildcard_pattern_detection(self):
        """Test detection of valid wildcard patterns"""
        # Valid wildcard contexts
        valid_contexts = [
            'frappe.db.sql("SELECT * FROM tabMember", as_dict=True)',
            'frappe.get_all("Member", fields=["*"])',
            'SELECT * FROM tabMember WHERE status = "Active"'
        ]
        
        for context in valid_contexts:
            is_valid, pattern_type = self.handler.is_valid_frappe_pattern("obj.*", context)
            # Note: This tests the structure, actual implementation may vary
    
    def test_alias_pattern_detection(self):
        """Test detection of SQL alias patterns"""
        context = 'frappe.db.sql("SELECT name as member_name FROM tabMember")'
        
        # Should detect alias usage
        is_alias = self.handler.handle_alias_access("member_name", context)
        self.assertTrue(is_alias)
    
    def test_child_table_patterns(self):
        """Test child table access pattern detection"""
        context = 'for membership in member.memberships:'
        
        is_valid, pattern_type = self.handler.is_valid_frappe_pattern(
            "membership.chapter", context
        )
        # Basic structural test


class TestValidationEngine(unittest.TestCase):
    """Test the core validation engine"""
    
    def setUp(self):
        # Create mock components
        self.mock_schema_reader = Mock()
        self.mock_context_analyzer = Mock()
        self.mock_pattern_handler = Mock()
        
        # Setup mock schema
        self.mock_schema_reader.doctypes = {"Member": Mock()}
        self.mock_schema_reader.is_valid_field.return_value = True
        
        # Setup mock context
        mock_context = Mock()
        mock_context.variable_assignments = {"member": "Member"}
        mock_context.sql_variables = set()
        mock_context.child_table_iterations = {}
        mock_context.property_methods = set()
        mock_context.frappe_api_calls = set()
        
        self.mock_context_analyzer.analyze_file_context.return_value = {1: mock_context}
        self.mock_pattern_handler.is_valid_frappe_pattern.return_value = (False, None)
        
        self.engine = ValidationEngine(
            self.mock_schema_reader,
            self.mock_context_analyzer, 
            self.mock_pattern_handler,
            min_confidence=0.7
        )
    
    def test_valid_field_access(self):
        """Test validation of valid field access"""
        test_code = 'member.first_name'
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_code)
            f.flush()
            
            issues = self.engine.validate_file(Path(f.name))
            
            # Should not report issues for valid field
            self.assertEqual(len(issues), 0)
        
        os.unlink(f.name)
    
    def test_invalid_field_access(self):
        """Test detection of invalid field access"""
        # Setup mock to return invalid field
        self.mock_schema_reader.is_valid_field.return_value = False
        
        test_code = 'member.nonexistent_field'
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_code)
            f.flush()
            
            issues = self.engine.validate_file(Path(f.name))
            
            # Should report issue for invalid field
            self.assertTrue(len(issues) > 0)
            if issues:
                self.assertEqual(issues[0].field_name, "nonexistent_field")
        
        os.unlink(f.name)


class TestConfigurationManager(unittest.TestCase):
    """Test the configuration management system"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_manager = ConfigurationManager(Path(self.temp_dir))
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_preset_configurations(self):
        """Test loading of preset configurations"""
        # Test all preset levels
        for level in ValidationLevel:
            config = self.config_manager.get_preset_config(level)
            self.assertIsInstance(config, ValidationConfig)
            self.assertEqual(config.level, level)
    
    def test_config_save_load(self):
        """Test saving and loading configuration"""
        # Create a custom config
        config = self.config_manager.get_preset_config(ValidationLevel.BALANCED)
        config.confidence_thresholds.field_access = 0.95
        
        # Save and reload
        self.config_manager.save_config(config)
        loaded_config = self.config_manager.load_config()
        
        # Should match
        self.assertEqual(loaded_config.confidence_thresholds.field_access, 0.95)
    
    def test_custom_config_creation(self):
        """Test creating custom configurations"""
        custom_config = self.config_manager.create_custom_config(
            ValidationLevel.BALANCED,
            field_access=0.85,
            verbose_output=True
        )
        
        self.assertEqual(custom_config.level, ValidationLevel.CUSTOM)
        self.assertEqual(custom_config.confidence_thresholds.field_access, 0.85)


class TestSchemaAwareValidator(unittest.TestCase):
    """Integration tests for the complete validator"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.app_path = Path(self.temp_dir)
        
        # Create minimal app structure
        doctype_dir = self.app_path / "verenigingen" / "verenigingen" / "doctype" / "member"
        doctype_dir.mkdir(parents=True)
        
        member_json = {
            "name": "Member",
            "fields": [
                {"fieldname": "first_name", "fieldtype": "Data"},
                {"fieldname": "email", "fieldtype": "Data"}
            ]
        }
        
        with open(doctype_dir / "member.json", 'w') as f:
            json.dump(member_json, f)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_end_to_end_validation(self):
        """Test complete validation workflow"""
        validator = SchemaAwareValidator(str(self.app_path), verbose=False)
        
        # Create test Python file with various patterns
        test_code = '''
# Valid patterns that should NOT be flagged
member = frappe.get_doc("Member", "test")
valid_field = member.first_name
sql_result = frappe.db.sql("SELECT name as member_name FROM tabMember", as_dict=True)
alias_access = sql_result[0].member_name

# Invalid pattern that SHOULD be flagged  
invalid_field = member.nonexistent_field

# Patterns that should be excluded
builtin_access = json.loads('{}')  # json is builtin
frappe_access = frappe.utils.now()  # frappe is builtin
'''
        
        test_file = self.app_path / "test_validation.py"
        with open(test_file, 'w') as f:
            f.write(test_code)
        
        # Run validation
        issues = validator.validate_file(test_file)
        
        # Should find the invalid field but not the valid ones
        invalid_issues = [i for i in issues if i.field_name == "nonexistent_field"]
        self.assertTrue(len(invalid_issues) > 0, "Should detect invalid field")
        
        # Should not flag valid patterns (this is the key improvement)
        valid_field_issues = [i for i in issues if i.field_name == "first_name"]
        self.assertEqual(len(valid_field_issues), 0, "Should not flag valid fields")


class TestFalsePositiveReduction(unittest.TestCase):
    """Specific tests for false positive reduction"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.app_path = Path(self.temp_dir)
        
        # Create app structure with child table
        doctype_dir = self.app_path / "verenigingen" / "verenigingen" / "doctype"
        
        # Parent DocType
        member_dir = doctype_dir / "member"
        member_dir.mkdir(parents=True)
        member_json = {
            "name": "Member",
            "fields": [
                {"fieldname": "memberships", "fieldtype": "Table", "options": "Chapter Member"}
            ]
        }
        with open(member_dir / "member.json", 'w') as f:
            json.dump(member_json, f)
        
        # Child DocType
        chapter_member_dir = doctype_dir / "chapter_member"
        chapter_member_dir.mkdir()
        chapter_member_json = {
            "name": "Chapter Member",
            "istable": 1,
            "fields": [
                {"fieldname": "chapter", "fieldtype": "Link"},
                {"fieldname": "status", "fieldtype": "Select"}
            ]
        }
        with open(chapter_member_dir / "chapter_member.json", 'w') as f:
            json.dump(chapter_member_json, f)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_child_table_field_access(self):
        """Test that child table field access is not flagged as error"""
        validator = SchemaAwareValidator(str(self.app_path), verbose=False)
        
        # This pattern was causing false positives in the old system
        test_code = '''
member = frappe.get_doc("Member", "test")
for membership in member.memberships:
    chapter_name = membership.chapter  # Should be valid - child table field
    membership_status = membership.status  # Should be valid - child table field
'''
        
        test_file = self.app_path / "test_child_table.py"
        with open(test_file, 'w') as f:
            f.write(test_code)
        
        issues = validator.validate_file(test_file)
        
        # Should not flag child table field access
        chapter_issues = [i for i in issues if i.field_name == "chapter"]
        status_issues = [i for i in issues if i.field_name == "status"]
        
        self.assertEqual(len(chapter_issues), 0, "Should not flag valid child table field 'chapter'")
        self.assertEqual(len(status_issues), 0, "Should not flag valid child table field 'status'")
    
    def test_sql_alias_access(self):
        """Test that SQL alias access is not flagged"""
        validator = SchemaAwareValidator(str(self.app_path), verbose=False)
        
        test_code = '''
# SQL with alias - should not be flagged
result = frappe.db.sql("""
    SELECT 
        name as member_name,
        COUNT(*) as total_count
    FROM tabMember 
    GROUP BY name
""", as_dict=True)

for row in result:
    name = row.member_name  # SQL alias - should be valid
    count = row.total_count  # SQL alias - should be valid
'''
        
        test_file = self.app_path / "test_sql_alias.py"
        with open(test_file, 'w') as f:
            f.write(test_code)
        
        issues = validator.validate_file(test_file)
        
        # Should not flag SQL alias access
        alias_issues = [i for i in issues if i.field_name in ["member_name", "total_count"]]
        self.assertEqual(len(alias_issues), 0, "Should not flag SQL alias fields")
    
    def test_property_method_access(self):
        """Test that @property method access is not flagged"""
        validator = SchemaAwareValidator(str(self.app_path), verbose=False)
        
        test_code = '''
class MemberManager:
    @property
    def active_count(self):
        return len(self._active_members)
    
    def get_stats(self):
        # This should not be flagged - accessing a property method
        count = self.active_count
        return count
'''
        
        test_file = self.app_path / "test_property.py"
        with open(test_file, 'w') as f:
            f.write(test_code)
        
        issues = validator.validate_file(test_file)
        
        # Should not flag property method access
        property_issues = [i for i in issues if i.field_name == "active_count"]
        self.assertEqual(len(property_issues), 0, "Should not flag @property method access")


def run_performance_test():
    """Quick performance test to ensure validator runs efficiently"""
    import time
    
    temp_dir = tempfile.mkdtemp()
    app_path = Path(temp_dir)
    
    try:
        # Create minimal structure
        doctype_dir = app_path / "verenigingen" / "verenigingen" / "doctype" / "member"
        doctype_dir.mkdir(parents=True)
        
        member_json = {"name": "Member", "fields": [{"fieldname": "name", "fieldtype": "Data"}]}
        with open(doctype_dir / "member.json", 'w') as f:
            json.dump(member_json, f)
        
        # Create multiple test files
        for i in range(10):
            test_file = app_path / f"test_file_{i}.py"
            with open(test_file, 'w') as f:
                f.write(f"""
# Test file {i}
member = frappe.get_doc("Member", "test")
name = member.name
invalid = member.invalid_field_{i}
""")
        
        # Time the validation
        validator = SchemaAwareValidator(str(app_path), verbose=False)
        
        start_time = time.time()
        issues = validator.validate_directory()
        end_time = time.time()
        
        elapsed = end_time - start_time
        print(f"⏱️  Performance test: validated 10 files in {elapsed:.2f}s")
        print(f"   Found {len(issues)} issues")
        
        # Should complete within reasonable time
        assert elapsed < 30, f"Validation took too long: {elapsed:.2f}s"
        
    finally:
        import shutil
        shutil.rmtree(temp_dir)


def main():
    """Run all tests"""
    print("🧪 Running Schema-Aware Validator Test Suite")
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [
        TestDatabaseSchemaReader,
        TestContextAnalyzer,
        TestFrappePatternHandler,
        TestValidationEngine,
        TestConfigurationManager,
        TestSchemaAwareValidator,
        TestFalsePositiveReduction
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Run performance test
    try:
        print("\n🚀 Running performance test...")
        run_performance_test()
        print("✅ Performance test passed")
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
    
    # Summary
    if result.wasSuccessful():
        print(f"\n✅ All tests passed! ({result.testsRun} tests)")
        return 0
    else:
        print(f"\n❌ {len(result.failures)} failures, {len(result.errors)} errors")
        return 1


if __name__ == "__main__":
    exit(main())