# Field Validation System

## Overview

The field validation system helps prevent runtime errors by validating that DocType field references in Python code actually exist in the schema.

## Components

### 1. Test-Time Validation (`verenigingen/tests/fixtures/field_validator.py`)
- Used during unit tests to validate field references
- Part of the Enhanced Test Factory
- Validates fields exist before creating test data
- Can be disabled for specific fields (e.g., custom fields)

### 2. Pre-Commit Validation (`scripts/pre_commit_field_validator.py`)
- Runs as a pre-commit hook
- Scans Python files for field references
- Reports errors for non-existent fields
- Provides warnings for ambiguous references

## Usage

### In Tests
```python
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

class MyTest(EnhancedTestCase):
    def test_something(self):
        # Field validation happens automatically
        member = self.create_test_member(
            first_name="John",
            invalid_field="value"  # This will raise an error
        )
```

### As Pre-Commit Hook
The validator runs automatically on commit if pre-commit is installed:
```bash
pre-commit install
```

### Manual Validation
```bash
# Validate specific files
python scripts/pre_commit_field_validator.py path/to/file.py

# Validate all Python files
python scripts/pre_commit_field_validator.py --all

# Show warnings
python scripts/pre_commit_field_validator.py -v path/to/file.py
```

## Field Reference Patterns

The validator detects various patterns:

1. **Attribute access**: `doc.field_name`, `member.email`
2. **Dictionary access**: `doc["field_name"]`, `data['status']`
3. **Get method**: `doc.get("field_name")`
4. **Database methods**: `doc.db_set("field_name", value)`
5. **Query filters**: `filters={"field_name": value}`

## Configuration

### Skipping Validation for Custom Fields

In test code:
```python
# Fields that might be custom or runtime fields
skip_validation_fields = {
    'chapter', 'suspension_reason', 'termination_reason', 
    'termination_date', 'join_date'
}
```

### Excluding Files from Pre-Commit

Update `.pre-commit-config.yaml`:
```yaml
- id: enhanced-field-validator
  exclude: '^(tests/|test_|.*_test\.py|debug_|.*_debug\.py|migrations/)'
```

## Benefits

1. **Early Error Detection**: Catch field reference errors before runtime
2. **Schema Compliance**: Ensure code stays in sync with DocType schemas
3. **Refactoring Safety**: Detect broken references when fields are renamed
4. **Documentation**: Field validation errors document expected schema

## Known Limitations

1. **Dynamic Fields**: Cannot validate dynamically generated field names
2. **Custom Fields**: May not detect fields added via Customize Form
3. **Child Tables**: Limited support for child table field validation
4. **Performance**: Large codebases may take time to validate

## Troubleshooting

### False Positives
If the validator reports errors for valid fields:
1. Check if the field is a custom field
2. Verify the DocType name is correct
3. Add the field to skip_validation_fields if needed

### Missing Schemas
If schemas aren't loading:
1. Ensure DocType JSON files exist
2. Check file permissions
3. Verify JSON syntax is valid

## Future Enhancements

1. **JavaScript Validation**: Extend to validate JS field references
2. **Custom Field Support**: Load custom fields from database
3. **IDE Integration**: Create plugins for VS Code/PyCharm
4. **Report Field Validation**: Validate fields in report queries
5. **Auto-Fix Suggestions**: Suggest correct field names for typos