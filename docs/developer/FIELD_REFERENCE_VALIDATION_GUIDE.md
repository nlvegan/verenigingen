# Field Reference Validation Guide

## Overview

This guide documents the enhanced field reference validation system implemented in January 2025, designed to catch invalid field references at development time and prevent runtime errors.

## Recent Critical Fixes

### System Alert DocType Field References
**Issue**: Invalid field references in System Alert doctype causing runtime errors.

**Files Fixed**:
- `verenigingen/www/monitoring_dashboard.py`
- `verenigingen/doctype/system_alert/system_alert.py`

**Problem**: Code was referencing `compliance_status` field which doesn't exist in the System Alert doctype.

```python
# ❌ BEFORE - Invalid field reference
def get_system_alerts_by_status(status):
    filters = {"docstatus": 1}
    if status:
        filters["compliance_status"] = status  # Field doesn't exist!

    return frappe.get_all("System Alert",
        filters=filters,
        fields=["name", "alert_message", "compliance_status"])  # Invalid field!
```

**Solution**: Use correct field name `severity` from DocType JSON.

```python
# ✅ AFTER - Correct field reference
def get_system_alerts_by_status(status):
    filters = {"docstatus": 1}
    if status:
        filters["severity"] = status  # Correct field name

    return frappe.get_all("System Alert",
        filters=filters,
        fields=["name", "alert_message", "severity"])  # Correct field!
```

### Payment History Event Handler Optimization
**Issue**: Inefficient full payment history rebuilds on every payment event.

**Problem**: Event handlers were doing complete rebuilds instead of atomic updates.

```python
# ❌ BEFORE - Inefficient full rebuild
def on_payment_entry_submit(doc, method):
    """Rebuild complete payment history on every payment"""
    load_payment_history(doc.party)  # Heavy operation
```

**Solution**: Use atomic update methods for better performance.

```python
# ✅ AFTER - Efficient atomic updates
def on_payment_entry_submit(doc, method):
    """Refresh only relevant financial history"""
    refresh_financial_history(doc.party, doc.name)  # Lightweight operation
```

## Validation Tools

### 1. Enhanced Field Validator
**Purpose**: Validates database field references in Python code.

```bash
# Run comprehensive field validation
python scripts/validation/enhanced_field_validator.py

# Focus on specific files
python scripts/validation/enhanced_field_validator.py --file verenigingen/api/my_module.py

# Pre-commit integration
python scripts/validation/enhanced_field_validator.py --pre-commit
```

**What it catches**:
- Invalid field names in `frappe.db.get_value()` calls
- Invalid field names in `frappe.db.get_all()` calls
- Invalid field names in `frappe.get_doc()` field access
- SQL queries with non-existent fields

### 2. Unified Field Validator
**Purpose**: Comprehensive AST + SQL analysis for field references.

```bash
# Full validation with AST and SQL analysis
python scripts/validation/unified_field_validator.py --pre-commit

# AST analysis only
python scripts/validation/unified_field_validator.py --ast-only

# SQL analysis only
python scripts/validation/unified_field_validator.py --sql-only
```

### 3. Hooks and Event Validator
**Purpose**: Special validation for event handlers and hooks.py.

```bash
# Validate hooks.py and event handlers
python scripts/validation/hooks_event_validator.py

# Check specific event handler methods
python scripts/validation/hooks_event_validator.py --method on_payment_entry_submit
```

## Development Workflow

### Before Writing Code
1. **Read DocType JSON**: Always check the DocType JSON file first to understand available fields.

```bash
# Check available fields for a DocType
cat verenigingen/doctype/system_alert/system_alert.json | jq '.fields[] | .fieldname'
```

2. **Use exact field names**: Never guess field names - use exactly what's in the JSON.

3. **Validate your code**: Run field validation before committing.

```bash
# Quick validation of your changes
python scripts/validation/enhanced_field_validator.py --file my_changed_file.py
```

### Pre-commit Integration
The validation system is automatically integrated into pre-commit hooks:

```yaml
# .pre-commit-config.yaml
- id: unified-field-validator
  name: Validate DocType field references (unified AST + SQL)
  entry: python scripts/validation/unified_field_validator.py --pre-commit
  language: system
  files: \.py$
  stages: [pre-commit]

- id: hooks-event-validator
  name: Validate hooks and event handlers
  entry: python scripts/validation/hooks_event_validator.py
  language: system
  files: '^(verenigingen/hooks\.py|verenigingen/events/.*\.py)$'
  stages: [pre-commit]

- id: fast-method-validator
  name: Fast method call validation
  entry: python scripts/validation/fast_method_validator.py
  language: system
  files: '\.py$'
  stages: [pre-commit]
```

**Automatic execution**:
- Field validation runs on all Python files when you commit
- Hooks/event validation runs when `hooks.py` or event files are modified
- Method validation runs on all Python files for deprecated method detection

### CI/CD Integration
Validation is integrated into the continuous integration pipeline:

```bash
# CI validation command
python scripts/validation/comprehensive_validator.py --quiet --field-only
```

## Special DocType Field Access Patterns

### Chapter DocType Field Access
The Chapter DocType has unique field access patterns that developers need to understand:

#### Document Name vs Display Name
```python
# Chapter DocType uses autoname: "prompt" and naming_rule: "Set by user"
# This means the document name (ID) IS the chapter name - there's no separate "chapter_name" field

# ✅ CORRECT - Use document name directly
chapter_doc = frappe.get_doc("Chapter", "Amsterdam")
chapter_name = chapter_doc.name  # "Amsterdam"

# ❌ INCORRECT - There is no "chapter_name" field
chapter_name = chapter_doc.chapter_name  # AttributeError!
```

#### Available Fields
Based on the Chapter DocType JSON, the actual fields are:
- `name` (document ID, acts as chapter name)
- `chapter_head` (Link to Member)
- `region` (Link to Region, required)
- `cost_center` (Link to Cost Center)
- `postal_codes` (Small Text)
- `board_members` (Table: Chapter Board Member)
- `introduction` (Text Editor, required)
- `meetup_embed_html` (Code)
- `address` (Text)
- `route` (Data)
- `published` (Check)
- `members` (Table: Chapter Member)

#### Correct Query Patterns
```python
# ✅ CORRECT - Query by document name
chapters = frappe.get_all("Chapter",
    fields=["name", "region", "chapter_head", "published"],
    filters={"published": 1})

# ✅ CORRECT - Access chapter data
chapter = frappe.get_doc("Chapter", chapter_name)
if chapter.published:
    region = chapter.region
    head = chapter.chapter_head

# ❌ INCORRECT - Using non-existent fields
chapter_data = frappe.db.get_value("Chapter", chapter_name,
    ["chapter_name", "is_active"])  # These fields don't exist!
```

#### Navigation and Relationships
```python
# ✅ CORRECT - Find chapters by region
chapters_in_region = frappe.get_all("Chapter",
    filters={"region": "Noord-Holland"},
    fields=["name", "chapter_head", "postal_codes"])

# ✅ CORRECT - Find chapter members
members = frappe.get_all("Chapter Member",
    filters={"parent": chapter_name},
    fields=["member", "role", "status"])
```

### Member DocType Common Patterns
```python
# Member DocType has both system fields and user-defined fields
member = frappe.get_doc("Member", member_name)

# ✅ Available system fields
member.name          # Document ID
member.first_name    # User data
member.last_name     # User data
member.email_address # User data
member.status        # Member status

# ❌ Common mistakes
member.chapter_name  # Use member.chapter instead
member.is_active     # Use member.status == "Active" instead
```

## Common Validation Errors and Fixes

### Error: Field Not Found in DocType
```bash
🔴 Error: Field 'compliance_status' not found in doctype 'System Alert'
   File: verenigingen/www/monitoring_dashboard.py, Line: 45
```

**Fix Process**:
1. Check the DocType JSON file:
   ```bash
   cat verenigingen/doctype/system_alert/system_alert.json | grep -A5 -B5 "fieldname"
   ```
2. Find the correct field name (e.g., `severity`)
3. Update your code to use the correct field
4. Re-run validation to confirm fix

### Error: Invalid SQL Field Reference
```bash
🔴 Error: SQL query references invalid field 'old_field_name' in table 'tabSystem Alert'
   File: verenigingen/api/monitoring.py, Line: 123
```

**Fix Process**:
1. Identify the SQL query with the invalid field
2. Check the corresponding DocType for correct field names
3. Update the SQL query
4. Test the query in console to ensure it works

### Error: Event Handler Method Issues
```bash
🔴 Error: Event handler method 'load_payment_history' not optimized for performance
   File: verenigingen/hooks.py, Line: 67
```

**Fix Process**:
1. Replace heavy operations with atomic updates
2. Use specific update methods instead of full rebuilds
3. Test performance impact
4. Update hooks.py with optimized method

## Best Practices

### 1. Always Read DocType JSON First
```python
# ❌ Don't guess field names
member_data = frappe.get_doc("Member", member_name)
if member_data.is_active:  # Field might not exist!
    pass

# ✅ Check JSON first, then use exact names
member_data = frappe.get_doc("Member", member_name)
if member_data.status == "Active":  # Correct field from JSON
    pass
```

### 2. Use Field Lists Explicitly
```python
# ❌ Avoid implicit field selection
members = frappe.get_all("Member")  # Gets only 'name' field

# ✅ Be explicit about required fields
members = frappe.get_all("Member",
    fields=["name", "first_name", "last_name", "status"])
```

### 3. Handle Field Validation Errors Properly
```python
# ❌ Don't ignore validation errors
try:
    doc.save()
except Exception:
    pass  # Silent failure!

# ✅ Handle validation errors appropriately
try:
    doc.save()
except frappe.ValidationError as e:
    frappe.log_error(f"Validation failed: {str(e)}")
    frappe.throw(f"Could not save document: {str(e)}")
```

### 4. Optimize Event Handlers
```python
# ❌ Heavy operations in event handlers
def on_submit(doc, method):
    rebuild_all_related_data(doc)  # Too heavy!

# ✅ Atomic updates in event handlers
def on_submit(doc, method):
    update_specific_fields(doc.name, {"status": "Submitted"})
```

## Validation Configuration

### Exception Handling
Sometimes you need to exclude certain files or patterns from validation:

```python
# scripts/validation/validation_config.py
FIELD_VALIDATION_EXCEPTIONS = {
    "scripts/testing/test_specific_file.py": [
        "test_field_name",  # Allow this field name in tests
    ],
    "scripts/debug/debug_module.py": "*",  # Skip entire file
}
```

### Performance Tuning
Validation performance can be monitored and tuned:

```bash
# Check validation performance
python scripts/validation/enhanced_field_validator.py --profile

# Run with timing information
time python scripts/validation/unified_field_validator.py --pre-commit
```

## Integration with Other Tools

### IDE Integration
You can integrate field validation with your IDE:

```bash
# VS Code task for field validation
{
    "label": "Validate Field References",
    "type": "shell",
    "command": "python scripts/validation/enhanced_field_validator.py --file ${file}",
    "group": "test"
}
```

### Git Hooks
Beyond pre-commit, you can use validation in other git hooks:

```bash
# pre-push hook
#!/bin/sh
python scripts/validation/comprehensive_validator.py --field-only --quiet
```

## Troubleshooting

### Validation Too Slow
If field validation is taking too long:

1. **Use field-only mode**: `--field-only` for faster validation
2. **Exclude test files**: Most validation configs already exclude test files
3. **Run on specific files**: Use `--file` parameter for targeted validation

### False Positives
If validation reports incorrect errors:

1. **Check exception configuration**: Add exceptions in `validation_config.py`
2. **Verify DocType JSON**: Ensure the DocType JSON is up to date
3. **Test manually**: Verify the field actually exists/doesn't exist

### Integration Issues
If pre-commit hooks are failing:

1. **Check Python environment**: Ensure all dependencies are installed
2. **Test standalone**: Run validation scripts directly first
3. **Check file paths**: Ensure paths in configuration are correct

## Future Improvements

### Planned Enhancements
- **Real-time IDE integration**: Live validation as you type
- **Smart suggestions**: Suggest correct field names for typos
- **Performance profiling**: Detailed performance analysis of validation
- **Custom rules**: User-defined validation patterns
- **Caching**: Cache DocType schemas for faster validation

### Contributing
To contribute to the validation system:

1. **Add new validators**: Create new validation scripts in `scripts/validation/`
2. **Improve existing validators**: Enhance detection patterns or performance
3. **Update documentation**: Keep this guide updated with new features
4. **Test thoroughly**: Ensure new validation doesn't break existing workflows

---

**Last Updated**: January 26, 2025
**Version**: Enhanced Field Validation v2.0
**Related Documentation**:
- [Code Validation System](../validation/CODE_VALIDATION_SYSTEM.md)
- [Testing Framework 2025](../TESTING_FRAMEWORK_2025.md)
- [Troubleshooting Guide](../troubleshooting/workspace-debugging.md)
