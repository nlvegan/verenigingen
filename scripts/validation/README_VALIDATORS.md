# Method and Field Validation Tools

This directory contains validation tools to ensure code quality and catch common programming errors.

## Validation Tools Overview

### 1. 🚀 Fast Method Validator (`fast_method_validator.py`)
**Purpose**: Quick validation for common method call issues  
**Runtime**: ~30 seconds  
**Best for**: Pre-commit hooks, daily development

```bash
# Run fast validation
python scripts/validation/fast_method_validator.py

# Validate single file
python scripts/validation/fast_method_validator.py path/to/file.py
```

**Detects**:
- Deprecated method calls (`calculate_next_billing_date`)
- Common typos (`delete_doc` → `delete`)  
- Suspicious patterns (`ignore_permissions=True`)
- Known nonexistent methods

### 2. 🔍 Comprehensive Method Validator (`method_call_validator.py`)
**Purpose**: Deep analysis of all method calls with signature database  
**Runtime**: 2-5 minutes  
**Best for**: Weekly reviews, major refactoring validation

```bash
# Quick mode (verenigingen only)
python scripts/validation/method_call_validator.py

# Comprehensive mode (includes Frappe core)  
python scripts/validation/method_call_validator.py --comprehensive

# Rebuild cache first
python scripts/validation/method_call_validator.py --rebuild-cache

# Validate single file
python scripts/validation/method_call_validator.py path/to/file.py
```

**Features**:
- **Method signature database**: Maps all available methods
- **Call pattern analysis**: Handles complex call patterns (chained, dynamic, etc.)
- **Similarity suggestions**: Suggests corrections for typos
- **Frappe-aware**: Understands framework-specific patterns
- **Caching system**: Builds once, validates fast

### 3. 🎯 Enhanced Field Validator (`enhanced_field_validator.py`)
**Purpose**: Validates field references against DocType definitions  
**Runtime**: ~45 seconds  
**Best for**: Preventing field reference errors

```bash
python scripts/validation/enhanced_field_validator.py
```

**Detects**:
- Deprecated field references (`next_billing_date`)
- Invalid field names in queries
- Template variable errors
- Dictionary key mismatches

## Recommended Usage Workflow

### For Daily Development:
```bash
# Before committing (automatic via pre-commit)
python scripts/validation/fast_method_validator.py
```

### For Weekly Code Review:
```bash
# Comprehensive analysis
python scripts/validation/method_call_validator.py --comprehensive
python scripts/validation/enhanced_field_validator.py
```

### For Major Refactoring:
```bash
# Full validation suite
python scripts/validation/method_call_validator.py --rebuild-cache --comprehensive
python scripts/validation/enhanced_field_validator.py
python scripts/validation/comprehensive_validator.py
```

## Integration

### Pre-commit Hooks
The validators are integrated into `.pre-commit-config.yaml`:

- **Pre-commit**: Fast method validator (30s)
- **Pre-push**: Enhanced field validator (45s)
- **Manual**: Comprehensive method validator (2-5min)

### CI/CD Integration
For continuous integration, use the fast validators:

```yaml
# Example GitHub Actions
- name: Validate method calls
  run: python scripts/validation/fast_method_validator.py

- name: Validate field references  
  run: python scripts/validation/enhanced_field_validator.py
```

## Performance Characteristics

| Validator | Runtime | Files Scanned | Methods Analyzed | Use Case |
|-----------|---------|---------------|------------------|----------|
| Fast Method | ~30s | 1,300+ | Pattern-based | Daily development |
| Comprehensive | 2-5min | 5,000+ | 10,000+ signatures | Weekly review |
| Enhanced Field | ~45s | 1,300+ | All field refs | Pre-push validation |

## Troubleshooting

### "Command timed out"
- Use fast validator for routine checks
- Run comprehensive validator manually when needed
- Consider `--rebuild-cache` if cache is corrupted

### False Positives
- Fast validator focuses on high-confidence issues
- Comprehensive validator has better context awareness
- Both validators skip test files and complex patterns

### Cache Issues
- Cache files stored in `scripts/validation/.method_cache.pkl`
- Cache expires after 1 hour automatically
- Use `--rebuild-cache` to force refresh

## Call Pattern Coverage

All validators handle these Python call patterns:

```python
# Simple calls
func()
obj.method()

# Complex patterns  
obj.attr.method()           # ✅ Chained access
func().method()             # ✅ Dynamic calls
obj[key]()                  # ✅ Subscript calls
(lambda x: x)()             # ✅ Lambda calls
"string".upper()            # ✅ Built-in methods
frappe.get_doc().save()     # ✅ Frappe patterns
```

## Extension

To add new validation rules:

1. **Fast validator**: Add patterns to `deprecated_methods` or `suspicious_patterns`
2. **Comprehensive validator**: Enhance `_is_likely_valid_pattern()` method
3. **Field validator**: Update `deprecated_fields` configuration

All validators follow the same pattern-based approach for easy maintenance and extension.