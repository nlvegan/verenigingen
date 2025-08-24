# DocType Field Validator - False Positive Reduction Plan

## Current State
- 294 issues reported, ~99% false positives
- Main issue: Incorrect DocType detection leading to wrong field validation

## Key Sources of False Positives

### 1. **Incorrect Child Table Context Detection**
**Problem**: When iterating over child tables, the validator incorrectly identifies the DocType
**Example**: 
```python
for chart in dashboard.charts:  # charts is Dashboard Chart Link, not Workspace Chart
    x = chart.chart  # Valid field, but validator thinks it's Workspace Chart
```
**Solution**: Improve child table detection by tracking parent.field → child DocType mappings more accurately

### 2. **Custom Fields**
**Problem**: Fields starting with `custom_` are added dynamically and not in JSON definitions
**Example**: `membership_dues_schedule_display`
**Solution**: 
- Query database for custom fields at runtime
- Or whitelist all `custom_*` fields by default

### 3. **SQL Aliases and Computed Fields**
**Problem**: SQL queries often return objects with different field names than the DocType
**Example**: `invoice_name` might be an alias in a SQL query
**Solution**: Better detect SQL context and skip validation for those objects

### 4. **Property Methods (@property)**
**Problem**: Properties look like field access but are actually methods
**Current Solution**: Already implemented but needs expansion
**Improvement**: Scan more thoroughly for @property decorators

### 5. **Variable Name to DocType Mapping**
**Problem**: Simple variable names don't always map correctly to DocTypes
**Example**: `chart` → assumes `Workspace Chart` instead of `Dashboard Chart Link`
**Solution**: Don't rely solely on variable names for DocType detection

## Proposed Implementation Approach

### Phase 1: Better Child Table Detection
```python
# Track the full context of child table iterations
# dashboard.charts returns Dashboard Chart Link, not Workspace Chart
# Need to track: parent_doctype.field_name → child_doctype
```

### Phase 2: Whitelist Common Patterns
```python
# Whitelist patterns that are almost always false positives:
whitelist_patterns = [
    r'custom_.*',  # All custom fields
    r'.*_name$',   # Common alias pattern (invoice_name, member_name)
    r'.*_id$',     # Common ID patterns
]
```

### Phase 3: Context-Aware Validation
```python
# Skip validation in certain contexts:
skip_contexts = [
    'frappe.db.sql',  # SQL results
    'json.loads',     # External JSON data
    'api_response',   # API responses
    '.get_all(*)',    # When using wildcards
]
```

### Phase 4: Focus on High-Value Validation
Instead of trying to validate everything, focus on the most common and important patterns:
- Direct `frappe.get_doc()` usage
- Simple field access on clearly identified DocTypes
- Skip ambiguous cases

## Quick Wins (Immediate Implementation)

1. **Fix Variable Name Mapping**
   - Remove overly broad mappings like `chart` → `Workspace Chart`
   - Only map when we have high confidence

2. **Improve Child Table Detection**
   - Track parent.field relationships better
   - Use the child_table_mapping more effectively

3. **Add Custom Field Whitelist**
   - Skip all `custom_*` fields
   - These are added at runtime and can't be validated statically

4. **Better SQL Context Detection**
   - Expand SQL pattern detection
   - Skip validation for objects in SQL context

## Expected Results
- Reduce false positives from ~99% to <20%
- Make the validator actually useful for catching real issues
- Focus on high-confidence issues only