# Pragmatic Field Validator Guide

## Overview

The Pragmatic Field Validator is a production-ready database field validation tool that builds on the existing improved validator with selective exclusions for common false positive patterns. It provides configurable validation levels to balance thoroughness with practical development workflow needs.

## Key Features

### 1. **Builds on Proven Foundation**
- Extends the `improved_frappe_api_validator.py` that already fixed genuine field reference issues
- Maintains all existing valid pattern recognition (wildcards, aliases, joined fields)
- Preserves high-value validation for critical business logic

### 2. **Selective Exclusion System**
- **Child table patterns**: Excludes `item.field` access in loop contexts
- **Property methods**: Skips validation in `@property` decorated functions
- **Dynamic references**: Handles `getattr`, `hasattr`, `setattr` patterns
- **Template contexts**: Excludes JavaScript/template variable references
- **Pattern-based**: Uses regex patterns rather than complex AST parsing

### 3. **Configurable Validation Levels**
- **Strict**: Minimal exclusions, catches everything possible
- **Balanced**: Practical exclusions for daily development (default)
- **Permissive**: Maximum exclusions, only critical issues

### 4. **Production Ready**
- Performance suitable for pre-commit hooks
- Clear error messages with context and suggestions
- Comprehensive statistics and reporting
- No false positive noise for developers

## Usage

### Command Line Interface

```bash
# Basic usage (balanced mode)
python scripts/validation/pragmatic_field_validator.py

# Specify validation level
python scripts/validation/pragmatic_field_validator.py --level strict
python scripts/validation/pragmatic_field_validator.py --level balanced
python scripts/validation/pragmatic_field_validator.py --level permissive

# Show validation statistics
python scripts/validation/pragmatic_field_validator.py --stats

# Custom app path
python scripts/validation/pragmatic_field_validator.py --app-path /path/to/app
```

### Pre-commit Integration

The validator is integrated into the pre-commit configuration:

```yaml
# Automatic validation on commit (balanced mode)
- id: frappe-api-validator
  name: Pragmatic database field validation (balanced)
  entry: python scripts/validation/pragmatic_field_validator.py --level balanced
  stages: [pre-commit]

# Manual strict validation
- id: pragmatic-field-validator-strict
  name: Pragmatic database field validation (strict mode)
  entry: python scripts/validation/pragmatic_field_validator.py --level strict
  stages: [manual]
```

### Running Pre-commit Hooks

```bash
# Run balanced validation (automatic on commit)
pre-commit run frappe-api-validator

# Run strict validation manually
pre-commit run pragmatic-field-validator-strict --all-files
```

## Validation Levels Explained

### Strict Mode
- **Purpose**: Maximum thoroughness, minimal exclusions
- **Use Case**: Code reviews, quality audits, before major releases
- **Exclusions**: Only excludes universally valid patterns (wildcards, aliases)
- **False Positives**: Higher, but catches edge cases
- **Command**: `--level strict`

### Balanced Mode (Default)
- **Purpose**: Practical daily development workflow
- **Use Case**: Pre-commit hooks, regular development
- **Exclusions**: Common false positive patterns
- **False Positives**: Minimal, developer-friendly
- **Command**: `--level balanced`

### Permissive Mode
- **Purpose**: Legacy code integration, rapid development
- **Use Case**: Large refactoring, legacy codebase onboarding
- **Exclusions**: Maximum exclusions for compatibility
- **False Positives**: Very rare, focuses on critical issues only
- **Command**: `--level permissive`

## What Gets Validated

### ✅ Always Validated (All Levels)
- Direct field references in `frappe.db.get_value()`
- Filter field references in `frappe.get_all()`
- Field lists in database query `fields` parameters
- Critical business logic field access

### ⚠️ Conditionally Validated (Level Dependent)
- Child table field access in loops (`item.field`)
- Property method field references (`@property def field`)
- Dynamic field access (`getattr`, `hasattr`)
- Template variable contexts (`{{field}}`)

### ❌ Never Validated (All Levels)
- Wildcard selections (`"*"` in field lists)
- Field aliases (`"field as alias"`)
- Joined field references (`"table.field"`)
- Conditional fields (`"eval:condition"`)
- SQL functions (`COUNT(field)`, `SUM(field)`)

## Exclusion Patterns

### Child Table Patterns
```python
# Excluded in balanced/permissive modes
for item in items:
    item.field_name  # ← Not validated

# Still validated in all modes
frappe.db.get_value("DocType", doc_name, "field_name")  # ← Always validated
```

### Property Method Patterns
```python
# Excluded in balanced/permissive modes
@property
def custom_field(self):
    return self.field_name  # ← Not validated

# Still validated in all modes
def regular_method(self):
    return frappe.db.get_value("DocType", self.name, "field_name")  # ← Always validated
```

### Dynamic Reference Patterns
```python
# Excluded in balanced/permissive modes
field_value = getattr(obj, "field_name", None)  # ← Not validated
has_field = hasattr(obj, "field_name")          # ← Not validated

# Still validated in all modes
field_value = frappe.db.get_value("DocType", name, "field_name")  # ← Always validated
```

## Configuration Examples

### Custom Configuration
```python
from scripts.validation.pragmatic_field_validator import (
    PragmaticDatabaseQueryValidator, 
    ValidationConfig, 
    ValidationLevel
)

# Create custom configuration
config = ValidationConfig(
    level=ValidationLevel.BALANCED,
    exclude_child_table_patterns=True,
    exclude_property_methods=True,
    exclude_dynamic_references=False,  # Validate dynamic refs
    exclude_template_contexts=True,
)

# Initialize validator
validator = PragmaticDatabaseQueryValidator("/path/to/app", config)
violations = validator.validate_app()
```

## Performance Characteristics

### Balanced Mode (Recommended)
- **Speed**: ~30 seconds for full app validation
- **Memory**: Low memory footprint
- **Accuracy**: High precision, minimal false positives
- **Developer Experience**: Smooth, actionable feedback

### Strict Mode
- **Speed**: ~35 seconds for full app validation
- **Memory**: Slightly higher due to additional pattern matching
- **Accuracy**: Maximum thoroughness
- **Developer Experience**: More false positives, requires expert review

### Permissive Mode
- **Speed**: ~25 seconds for full app validation
- **Memory**: Lowest memory usage
- **Accuracy**: Focuses on critical issues only
- **Developer Experience**: Minimal interruption

## Migration from Existing Validators

### From `improved_frappe_api_validator.py`
```bash
# Old command
python scripts/validation/improved_frappe_api_validator.py

# New command (equivalent functionality)
python scripts/validation/pragmatic_field_validator.py --level strict
```

### From Legacy Validators
```bash
# Replace multiple validators with single pragmatic validator
python scripts/validation/pragmatic_field_validator.py --level balanced --stats
```

## Error Message Format

```
❌ Found 5 field reference issues:
--------------------------------------------------------------------------------
📁 api/member_management.py:156
   🏷️  Member.current_chapter - Field 'current_chapter' does not exist in Member
   📋 filter_field in frappe.get_all()
   💾 members = frappe.get_all("Member", filters={"current_chapter": chapter})
   💡 Suggestions: chapter_reference, membership_chapter, primary_chapter
   ⚙️  Level: balanced
```

### Error Components
- **📁 File and line**: Location of the issue
- **🏷️ Field reference**: DocType and field that's invalid
- **📋 Issue type**: filter_field, select_field, etc.
- **💾 Context**: Code line showing the issue
- **💡 Suggestions**: Top 5 valid field alternatives
- **⚙️ Level**: Validation level that caught this issue

## Best Practices

### Development Workflow
1. **Daily Development**: Use balanced mode in pre-commit hooks
2. **Code Reviews**: Run strict mode before pull requests
3. **Legacy Integration**: Start with permissive mode, gradually increase strictness
4. **CI/CD**: Use balanced mode for automated testing

### Field Reference Guidelines
1. **Always verify field names** against DocType JSON before coding
2. **Use exact field names** from DocType definitions
3. **Prefer explicit field lists** over wildcard selections when possible
4. **Test field references** in development environment

### Exclusion Management
1. **Review exclusions periodically** to ensure they're still appropriate
2. **Use strict mode** for final quality checks
3. **Document intentional exclusions** in code comments
4. **Monitor exclusion effectiveness** with statistics

## Troubleshooting

### Common Issues

#### "Field does not exist" Errors
```bash
# Verify field exists in DocType JSON
python -c "
import json
with open('verenigingen/doctype/member/member.json') as f:
    data = json.load(f)
    fields = [f['fieldname'] for f in data['fields']]
    print('Available fields:', sorted(fields))
"
```

#### Too Many False Positives
```bash
# Try more permissive level
python scripts/validation/pragmatic_field_validator.py --level permissive

# Or check what exclusions are active
python scripts/validation/pragmatic_field_validator.py --stats
```

#### Performance Too Slow
```bash
# Use balanced mode instead of strict
python scripts/validation/pragmatic_field_validator.py --level balanced

# Focus on specific files/patterns
python scripts/validation/pragmatic_field_validator.py --level balanced | head -20
```

### Debug Mode
```bash
# Run with verbose statistics
python scripts/validation/pragmatic_field_validator.py --stats --level balanced

# Check configuration
python -c "
from scripts.validation.pragmatic_field_validator import ValidationConfig, ValidationLevel
config = ValidationConfig.for_level(ValidationLevel.BALANCED)
print('Exclusions enabled:')
for attr, value in config.__dict__.items():
    if attr.startswith('exclude_'):
        print(f'  {attr}: {value}')
"
```

## Integration with Other Tools

### IDE Integration
Most IDEs can run the validator as an external tool:

```bash
# VS Code tasks.json
{
    "label": "Validate Database Fields",
    "type": "shell",
    "command": "python",
    "args": ["scripts/validation/pragmatic_field_validator.py", "--level", "balanced"],
    "group": "build",
    "presentation": {
        "echo": true,
        "reveal": "always",
        "focus": false,
        "panel": "shared"
    }
}
```

### CI/CD Pipeline
```yaml
# GitHub Actions example
- name: Validate Database Fields
  run: |
    python scripts/validation/pragmatic_field_validator.py --level balanced
    if [ $? -ne 0 ]; then
      echo "Field validation failed. Please fix field references."
      exit 1
    fi
```

## Contributing

### Adding New Exclusion Patterns
1. Identify the pattern causing false positives
2. Create a regex pattern in `_build_exclusion_patterns()`
3. Add appropriate configuration flag
4. Test with all validation levels
5. Document the exclusion in this guide

### Modifying Validation Logic
1. Extend the base validator methods
2. Maintain backward compatibility
3. Add comprehensive tests  
4. Update documentation
5. Consider performance impact

## Support

For questions, issues, or contributions related to the Pragmatic Field Validator:

1. **Check this documentation** first
2. **Run with `--stats`** to understand current configuration
3. **Try different validation levels** to isolate issues
4. **Review error messages** for specific field suggestions
5. **Check DocType JSON files** to verify field names

The Pragmatic Field Validator is designed to be a reliable, developer-friendly tool that catches real field reference issues while minimizing false positive noise in daily development workflows.